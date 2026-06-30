"""
Telegram notification helpers.

Reads TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from environment.
Uses plain httpx (already a project dependency) — no extra SDK needed.
"""

import os
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


def _failure_hint(error_sample: str | None) -> str:
    """Turn a raw analyst error into a short, actionable hint."""
    if not error_sample:
        return "check API status"
    s = error_sample.lower()
    if "credit balance" in s or "too low" in s:
        return "Anthropic credits exhausted — top up Plans &amp; Billing"
    if "429" in s or "rate" in s or "overloaded" in s:
        return "rate limited / overloaded"
    if "401" in s or "authentication" in s or "api key" in s or "api_key" in s:
        return "auth / API key problem"
    return error_sample[:80]


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

    if not decisions:
        return header + "\n\nNo actionable markets found."

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

    return "\n".join(lines)


async def send_telegram_message(text: str) -> dict[str, Any]:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        return {"ok": False, "error": "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set"}

    url = f"{TELEGRAM_API}/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(url, json=payload)
        return response.json()
