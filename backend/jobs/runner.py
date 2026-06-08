"""
Experiment runner — executes one full pipeline cycle:
  sync markets → score → research → claude analyst
  → openai challenger → consensus → persist
"""

from datetime import datetime, timezone
from typing import Any

from agents.claude_analyst import analyze_markets
from agents.consensus_agent import run_consensus
from agents.openai_challenger import challenge_markets
from agents.research_agent import research_markets
from agents.simple_filter import score_markets
from backend.collectors.polymarket import sync_markets
from backend.db.agent_history import save_agent_run, save_consensus_decision
from backend.db.paper_portfolio import create_paper_trade_from_decision
from backend.notifications.telegram import format_experiment_summary, send_telegram_message
from backend.scanner import get_candidates

SYNC_LIMIT = 50
CYCLE_MARKET_LIMIT = 3  # max markets analyzed per cycle


def _filter_markets(researched: list, limit: int) -> list:
    return [
        m for m in researched
        if m.get("research", {}).get("modelable", False)
        and m.get("risk_flag") != "skip"
    ][:limit]


async def run_experiment_cycle(notify: bool = False) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc)

    # 1. Sync latest markets from Polymarket
    try:
        sync_result = await sync_markets(limit=SYNC_LIMIT)
    except Exception as exc:
        sync_result = {"fetched": 0, "error": str(exc)}

    # 2. Score, research, filter
    candidates = get_candidates(limit=CYCLE_MARKET_LIMIT * 4)
    scored = score_markets(candidates)
    researched = research_markets(scored)
    filtered = _filter_markets(researched, CYCLE_MARKET_LIMIT)

    if not filtered:
        summary = {
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": 0.0,
            "sync": sync_result,
            "markets_analyzed": 0,
            "decisions": [],
            "status": "no_markets",
        }
        if notify:
            try:
                text = format_experiment_summary(summary)
                tg_result = await send_telegram_message(text)
                summary["notification"] = tg_result
            except Exception as exc:
                summary["notification_error"] = str(exc)
        return summary

    # 3. Full pipeline
    with_analyst = analyze_markets(filtered)
    with_challenger = challenge_markets(with_analyst)
    results = run_consensus(with_challenger)

    # 4. Persist and build summary
    decisions = []
    for item in results:
        market_id = item["id"]
        analyst = item.get("analyst") or {}
        challenger = item.get("challenger") or {}
        consensus = item.get("consensus") or {}

        try:
            save_agent_run(market_id, analyst)
        except Exception:
            pass
        try:
            save_agent_run(market_id, challenger)
        except Exception:
            pass
        paper_trade = None
        try:
            decision_id = save_consensus_decision(market_id, consensus)
            if consensus.get("decision") == "BET":
                paper_trade = create_paper_trade_from_decision(
                    {**consensus, "id": decision_id, "market_id": market_id}
                )
        except Exception:
            pass

        decisions.append({
            "market_id": market_id,
            "question": item.get("question", ""),
            "yes_price": item.get("yes_price"),
            "claude_probability": consensus.get("claude_probability"),
            "challenger_probability": consensus.get("challenger_probability"),
            "consensus_probability": consensus.get("consensus_probability"),
            "edge": consensus.get("edge"),
            "confidence": consensus.get("confidence"),
            "recommended_side": consensus.get("recommended_side"),
            "decision": consensus.get("decision"),
            "paper_trade": paper_trade,
        })

    finished_at = datetime.now(timezone.utc)

    summary = {
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": round(
            (finished_at - started_at).total_seconds(), 1
        ),
        "sync": sync_result,
        "markets_analyzed": len(decisions),
        "decisions": decisions,
        "status": "ok",
    }

    if notify:
        try:
            text = format_experiment_summary(summary)
            tg_result = await send_telegram_message(text)
            summary["notification"] = tg_result
        except Exception as exc:
            summary["notification_error"] = str(exc)

    return summary
