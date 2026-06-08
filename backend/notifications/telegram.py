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


def format_experiment_summary(summary: dict[str, Any]) -> str:
    status = summary.get("status", "unknown")
    duration = summary.get("duration_seconds", 0)
    sync = summary.get("sync") or {}
    markets_synced = sync.get("markets_inserted_or_updated", sync.get("fetched", 0))
    markets_analyzed = summary.get("markets_analyzed", 0)
    decisions = summary.get("decisions", [])

    header = (
        f"🤖 <b>Polymarket AI Desk</b>\n"
        f"Status: <b>{status}</b> | Duration: {duration}s\n"
        f"Synced: {markets_synced} markets | Analyzed: {markets_analyzed}"
    )

    if not decisions:
        return header + "\n\nNo actionable markets found."

    lines = [header, "", "📊 <b>Decisions:</b>"]
    for i, d in enumerate(decisions, 1):
        question = d.get("question", "Unknown market")
        # truncate long questions
        if len(question) > 60:
            question = question[:57] + "..."

        decision = d.get("decision") or "?"
        emoji = DECISION_EMOJI.get(decision, "❓")
        side = d.get("recommended_side") or "?"
        yes_price = _pct(d.get("yes_price"))
        consensus = _pct(d.get("consensus_probability"))
        edge = _edge_str(d.get("edge"))

        lines.append(
            f"\n{i}. {question}\n"
            f"   Market {yes_price} → Consensus {consensus} | Edge {edge}\n"
            f"   {emoji} <b>{decision}</b>  Side: {side}"
        )

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
