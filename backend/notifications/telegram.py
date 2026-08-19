"""
Telegram notification helpers.

Reads TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from environment.
Uses plain httpx (already a project dependency) — no extra SDK needed.
"""

import html
import os
import re
from typing import Any

import httpx

TELEGRAM_API = "https://api.telegram.org"


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def _money(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{'+' if value >= 0 else '-'}${abs(value):.2f}"


def _portfolio_block(summary: dict[str, Any]) -> str:
    """P&L портфеля: выигрыши/проигрыши, реализованный + нереализованный, итог."""
    p = summary.get("portfolio") or {}
    if not p or "error" in p:
        return ""

    open_n = p.get("open_trades", 0)
    closed_n = p.get("closed_trades", 0)
    wins = p.get("wins", 0)
    losses = p.get("losses", 0)
    realized = float(p.get("realized_pnl") or 0)
    unrealized = float(p.get("unrealized_pnl") or 0)
    net = float(p.get("net_pnl") or 0)

    lines = [
        "💼 <b>Портфель</b>",
        f"Открыто: {open_n} · Закрыто: {closed_n} ({wins}П / {losses}М)",
        f"Реализ.: {_money(realized)} · Нереализ.: {_money(unrealized)}"
        f" · Итог: <b>{_money(net)}</b>",
    ]

    res = summary.get("resolution") or {}
    if res.get("resolved"):
        lines.append(
            f"✅ Закрыто в этом цикле: {res['resolved']} "
            f"({res.get('wins', 0)}П / {res.get('losses', 0)}М) "
            f"{_money(res.get('realized_pnl_delta'))}"
        )
    return "\n".join(lines)


def _timeline_block(summary: dict[str, Any]) -> str:
    """Сроки резолюции: ближайшее закрытие, в этом месяце, без даты."""
    tl = (summary.get("portfolio") or {}).get("timeline") or {}
    nearest = tl.get("nearest")
    if not nearest and not tl.get("no_date"):
        return ""

    lines = ["⏳ <b>Сроки</b>"]
    if nearest:
        q = nearest["question"]
        if len(q) > 48:
            q = q[:45] + "…"
        days = nearest["days"]
        when = f"через {days} дн" if days >= 0 else f"{-days} дн назад"
        lines.append(f"Ближайшее: {q} · {nearest['end_date']} ({when})")
    lines.append(
        f"В этом месяце: {tl.get('resolving_30d', 0)} · Без даты: {tl.get('no_date', 0)}"
    )
    return "\n".join(lines)


def _new_bets_block(summary: dict[str, Any]) -> str:
    """Новые ставки этого цикла (решения, по которым открылась paper-сделка)."""
    new_bets = [d for d in summary.get("decisions", []) if d.get("paper_trade")]
    if not new_bets:
        return "🎯 <b>Новые ставки</b>\nНет"

    lines = [f"🎯 <b>Новые ставки: {len(new_bets)}</b>"]
    for d in new_bets:
        q = d.get("question", "рынок")
        if len(q) > 48:
            q = q[:45] + "…"
        pt = d.get("paper_trade") or {}
        side = pt.get("side") or d.get("recommended_side") or "?"
        entry = _pct(pt.get("entry_probability"))
        lines.append(f"• {q} — {side}, вход {entry}")
    return "\n".join(lines)


def _failure_hint(error_sample: str | None) -> str:
    """Turn a raw analyst error into a short, actionable hint."""
    if not error_sample:
        return "check API status"
    s = error_sample.lower()
    if "credit balance" in s or "too low" in s:
        return "Баланс Anthropic исчерпан — пополни Plans &amp; Billing"
    if "429" in s or "rate" in s or "overloaded" in s:
        return "лимит запросов / перегрузка"
    if "403" in s or "forbidden" in s or "not allowed" in s:
        # Anthropic surfaces an empty balance as 403 as well as via the 400
        # "credit balance too low" message, so point at both.
        return "доступ к API запрещён (403) — проверь ключ и баланс Anthropic"
    if "401" in s or "authentication" in s or "api key" in s or "api_key" in s:
        return "проблема авторизации / ключа"
    # Unknown error: HTML-escape the raw snippet so it can't break parse_mode.
    return html.escape(error_sample[:80])


_STATUS_RU = {"ok": "ок", "degraded": "деградация", "no_markets": "нет рынков"}


def format_experiment_summary(summary: dict[str, Any]) -> str:
    """
    Сводка цикла для Telegram: новые ставки + сроки резолюции + P&L портфеля.
    Список всех решений в сообщение не выводится — он целиком в БД / дашборде.
    """
    status = summary.get("status", "unknown")
    duration = summary.get("duration_seconds", 0)
    sync = summary.get("sync") or {}
    markets_synced = sync.get("markets_inserted_or_updated", sync.get("fetched", 0))
    markets_analyzed = summary.get("markets_analyzed", 0)
    analyst_failures = summary.get("analyst_failures", 0)
    skipped_recent = len(summary.get("skipped_recent_market_ids", []))
    cooldown_line = f" · пропущено (кулдаун): {skipped_recent}" if skipped_recent else ""

    # Баннер деградации — цикл, который «завершился», но не дал анализа
    # (например, исчерпан баланс), не должен выглядеть обычным тихим днём.
    banner = ""
    if status == "degraded" or analyst_failures:
        hint = _failure_hint(summary.get("analyst_error_sample"))
        banner = (
            f"⚠️ <b>ДЕГРАДАЦИЯ</b> — аналитик упал "
            f"{analyst_failures}/{markets_analyzed}\n{hint}\n\n"
        )

    header = (
        f"{banner}"
        f"🤖 <b>Polymarket AI Desk</b>\n"
        f"Статус: <b>{_STATUS_RU.get(status, status)}</b> · {duration}с\n"
        f"Синхр.: {markets_synced} · проанализировано: {markets_analyzed}{cooldown_line}"
    )

    blocks = [header, _new_bets_block(summary), _timeline_block(summary),
              _portfolio_block(summary)]
    return "\n\n".join(b for b in blocks if b)


async def _tg_post(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(url, json=payload)
        try:
            return response.json()
        except Exception:
            return {"ok": False, "error": f"non-JSON response (HTTP {response.status_code})"}


async def send_telegram_message(text: str) -> dict[str, Any]:
    """
    Send a message, never raising. Tries rich HTML first; if that fails to parse
    or errors, retries as plain text so an alert (e.g. the degradation banner)
    always gets through. Any HTML failure is recorded under `html_error`.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        return {"ok": False, "error": "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set"}

    url = f"{TELEGRAM_API}/bot{token}/sendMessage"
    base = {"chat_id": chat_id, "disable_web_page_preview": True}

    # Attempt 1: rich HTML
    html_error: Any = None
    try:
        result = await _tg_post(url, {**base, "text": text, "parse_mode": "HTML"})
        if result.get("ok"):
            return result
        html_error = result.get("description", result)
    except Exception as exc:
        html_error = repr(exc)

    # Attempt 2: plain text (strip tags, no parse_mode) — guarantees delivery
    # even if the HTML message failed to parse or the send raised.
    plain = re.sub(r"<[^>]+>", "", text)
    try:
        result = await _tg_post(url, {**base, "text": plain})
    except Exception as exc:
        return {"ok": False, "error": repr(exc), "html_error": html_error}

    result["fallback"] = "plain_text"
    result["html_error"] = html_error
    return result
