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

DECISION_EMOJI = {
    "BET": "🎯",
    "WATCH": "👀",
    "SKIP": "⏭",
    "NEEDS_MORE_RESEARCH": "🔍",
}


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def _edge_str(edge: float | None) -> str:
    if edge is None:
        return "n/a"
    sign = "+" if edge >= 0 else ""
    return f"{sign}{edge * 100:.1f}%"


def _money(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{'+' if value >= 0 else '-'}${abs(value):.2f}"


def _portfolio_block(summary: dict[str, Any]) -> str:
    """Operational P&L block: wins/losses, realized + unrealized, net."""
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
        "💼 <b>Portfolio</b>",
        f"Open: {open_n} | Closed: {closed_n} ({wins}W / {losses}L)",
        f"Realized: {_money(realized)} | Unrealized: {_money(unrealized)}"
        f" | Net: <b>{_money(net)}</b>",
    ]

    res = summary.get("resolution") or {}
    if res.get("resolved"):
        lines.append(
            f"✅ Resolved this cycle: {res['resolved']} "
            f"({res.get('wins', 0)}W / {res.get('losses', 0)}L) "
            f"{_money(res.get('realized_pnl_delta'))}"
        )
    return "\n".join(lines)


def _failure_hint(error_sample: str | None) -> str:
    """Turn a raw analyst error into a short, actionable hint."""
    if not error_sample:
        return "check API status"
    s = error_sample.lower()
    if "credit balance" in s or "too low" in s:
        return "Anthropic credits exhausted — top up Plans &amp; Billing"
    if "429" in s or "rate" in s or "overloaded" in s:
        return "rate limited / overloaded"
    if "403" in s or "forbidden" in s or "not allowed" in s:
        return "API access forbidden (403) — check the Anthropic API key"
    if "401" in s or "authentication" in s or "api key" in s or "api_key" in s:
        return "auth / API key problem"
    # Unknown error: HTML-escape the raw snippet so it can't break parse_mode.
    return html.escape(error_sample[:80])


def format_experiment_summary(summary: dict[str, Any]) -> str:
    """
    Compact Telegram summary for experiment runs.

    Header shows key counters. Body shows top-5 decisions by absolute edge.
    All decisions are always persisted to DB regardless of what is shown here.
    """
    status = summary.get("status", "unknown")
    duration = summary.get("duration_seconds", 0)
    sync = summary.get("sync") or {}
    markets_synced = sync.get("markets_inserted_or_updated", sync.get("fetched", 0))
    markets_analyzed = summary.get("markets_analyzed", 0)
    decisions = summary.get("decisions", [])
    analyst_failures = summary.get("analyst_failures", 0)

    bet_count = sum(1 for d in decisions if d.get("decision") == "BET")
    paper_trades_opened = summary.get("paper_trades_opened", bet_count)
    skipped_recent = len(summary.get("skipped_recent_market_ids", []))

    skipped_line = f" | Skipped (cooldown): {skipped_recent}" if skipped_recent else ""

    # Degradation banner first — a cycle that "completed" but produced no real
    # analysis (e.g. exhausted credits) must not look like a normal quiet day.
    banner = ""
    if status == "degraded" or analyst_failures:
        hint = _failure_hint(summary.get("analyst_error_sample"))
        banner = (
            f"⚠️ <b>DEGRADED</b> — analyst failed "
            f"{analyst_failures}/{markets_analyzed}\n{hint}\n\n"
        )

    header = (
        f"{banner}"
        f"🤖 <b>Polymarket AI Desk</b>\n"
        f"Status: <b>{status}</b> | {duration}s\n"
        f"Synced: {markets_synced} | Analyzed: {markets_analyzed}{skipped_line}\n"
        f"🎯 BET: {bet_count} | 💵 Paper trades: {paper_trades_opened}"
    )

    portfolio_block = _portfolio_block(summary)
    portfolio_tail = ("\n\n" + portfolio_block) if portfolio_block else ""

    if not decisions:
        return header + "\n\nNo actionable markets found." + portfolio_tail

    # Top 5 by absolute edge — most interesting regardless of direction
    top5 = sorted(decisions, key=lambda d: abs(d.get("edge") or 0), reverse=True)[:5]

    lines = [header, "", "📊 <b>Top decisions by edge:</b>"]
    for i, d in enumerate(top5, 1):
        question = d.get("question", "Unknown market")
        if len(question) > 55:
            question = question[:52] + "..."

        decision = d.get("decision") or "?"
        emoji = DECISION_EMOJI.get(decision, "❓")
        side = d.get("recommended_side") or "?"
        yes_price = _pct(d.get("yes_price"))
        consensus = _pct(d.get("consensus_probability"))
        edge = _edge_str(d.get("edge"))
        trade_tag = " 💵" if d.get("paper_trade") else ""

        lines.append(
            f"\n{i}. {question}\n"
            f"   {yes_price} → {consensus} | Edge {edge}\n"
            f"   {emoji} <b>{decision}</b>  {side}{trade_tag}"
        )

    total = len(decisions)
    if total > 5:
        lines.append(f"\n…and {total - 5} more saved to DB.")

    return "\n".join(lines) + portfolio_tail


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
