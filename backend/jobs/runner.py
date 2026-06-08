"""
Experiment runner — executes one full pipeline cycle:
  sync markets → score → research → cooldown filter → diverse select
  → claude analyst → openai challenger → consensus → persist

Configuration is read from backend/config.py (environment variables with safe defaults).
"""

from datetime import datetime, timezone
from typing import Any

from agents.claude_analyst import analyze_markets
from agents.consensus_agent import run_consensus
from agents.openai_challenger import challenge_markets
from agents.research_agent import research_markets
from agents.simple_filter import score_markets, select_diverse_candidates
from backend.collectors.polymarket import sync_markets
from backend.config import (
    EXPERIMENT_MARKET_LIMIT,
    EXPERIMENT_REANALYZE_COOLDOWN_HOURS,
    EXPERIMENT_SYNC_LIMIT,
    PAPER_TRADE_STAKE_USD,
)
from backend.db.agent_history import save_agent_run, save_consensus_decision
from backend.db.analytics import get_recently_analyzed_market_ids
from backend.db.paper_portfolio import create_paper_trade_from_decision
from backend.notifications.telegram import format_experiment_summary, send_telegram_message
from backend.scanner import get_candidates


async def run_experiment_cycle(
    notify: bool = False,
    sync_limit: int | None = None,
    market_limit: int | None = None,
) -> dict[str, Any]:
    """
    Run one full experiment cycle.

    Parameters
    ----------
    notify
        If True, send a Telegram summary after the cycle completes.
    sync_limit
        Override EXPERIMENT_SYNC_LIMIT for this run.
    market_limit
        Override EXPERIMENT_MARKET_LIMIT for this run.

    Returns a summary dict with keys:
      started_at, finished_at, duration_seconds,
      sync_limit, requested_market_limit, cooldown_hours,
      sync, markets_analyzed, analyzed_market_ids,
      skipped_recent_market_ids, decisions,
      paper_trades_opened, status
    """
    _sync_limit = sync_limit if sync_limit is not None else EXPERIMENT_SYNC_LIMIT
    _market_limit = market_limit if market_limit is not None else EXPERIMENT_MARKET_LIMIT
    _cooldown_hours = EXPERIMENT_REANALYZE_COOLDOWN_HOURS
    _stake = PAPER_TRADE_STAKE_USD

    started_at = datetime.now(timezone.utc)

    # 1. Sync latest markets from Polymarket
    try:
        sync_result = await sync_markets(limit=_sync_limit)
    except Exception as exc:
        sync_result = {"fetched": 0, "error": str(exc)}

    # 2. Fetch candidates, score, research
    #    Fetch generously so diversity selection has enough material.
    candidates = get_candidates(limit=_market_limit * 12)
    scored = score_markets(candidates)
    researched = research_markets(scored)

    # 3. Filter: modelable and not skip-flagged
    eligible = [
        m for m in researched
        if m.get("research", {}).get("modelable", False)
        and m.get("risk_flag") != "skip"
    ]

    # 4. Cooldown: skip markets analyzed within the cooldown window
    recent_ids = get_recently_analyzed_market_ids(_cooldown_hours)
    skipped_recent_ids = [m["id"] for m in eligible if m["id"] in recent_ids]
    fresh = [m for m in eligible if m["id"] not in recent_ids]

    # 5. Diverse selection (round-robin by category_guess)
    selected = select_diverse_candidates(fresh, _market_limit)

    if not selected:
        finished_at = datetime.now(timezone.utc)
        summary: dict[str, Any] = {
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "duration_seconds": round((finished_at - started_at).total_seconds(), 1),
            "sync_limit": _sync_limit,
            "requested_market_limit": _market_limit,
            "cooldown_hours": _cooldown_hours,
            "sync": sync_result,
            "markets_analyzed": 0,
            "analyzed_market_ids": [],
            "skipped_recent_market_ids": skipped_recent_ids,
            "decisions": [],
            "paper_trades_opened": 0,
            "status": "no_markets",
        }
        if notify:
            try:
                text = format_experiment_summary(summary)
                tg = await send_telegram_message(text)
                summary["notification"] = tg
            except Exception as exc:
                summary["notification_error"] = str(exc)
        return summary

    # 6. Full agent pipeline
    with_analyst = analyze_markets(selected)
    with_challenger = challenge_markets(with_analyst)
    results = run_consensus(with_challenger)

    # 7. Persist and build decision list
    decisions: list[dict[str, Any]] = []
    paper_trades_opened = 0

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

        paper_trade: dict[str, Any] | None = None
        try:
            decision_id = save_consensus_decision(market_id, consensus)
            if consensus.get("decision") == "BET":
                paper_trade = create_paper_trade_from_decision(
                    {**consensus, "id": decision_id, "market_id": market_id},
                    stake_usd=_stake,
                )
                if paper_trade:
                    paper_trades_opened += 1
        except Exception:
            pass

        decisions.append({
            "market_id": market_id,
            "question": item.get("question", ""),
            "category_guess": item.get("category_guess", "unknown"),
            "yes_price": item.get("yes_price"),
            "claude_probability": consensus.get("claude_probability"),
            "challenger_probability": consensus.get("challenger_probability"),
            "consensus_probability": consensus.get("consensus_probability"),
            "edge": consensus.get("edge"),
            "confidence": consensus.get("confidence"),
            "recommended_side": consensus.get("recommended_side"),
            "decision": consensus.get("decision"),
            "reason": consensus.get("reason"),
            "paper_trade": paper_trade,
        })

    finished_at = datetime.now(timezone.utc)

    summary = {
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": round((finished_at - started_at).total_seconds(), 1),
        "sync_limit": _sync_limit,
        "requested_market_limit": _market_limit,
        "cooldown_hours": _cooldown_hours,
        "sync": sync_result,
        "markets_analyzed": len(decisions),
        "analyzed_market_ids": [d["market_id"] for d in decisions],
        "skipped_recent_market_ids": skipped_recent_ids,
        "decisions": decisions,
        "paper_trades_opened": paper_trades_opened,
        "status": "ok",
    }

    if notify:
        try:
            text = format_experiment_summary(summary)
            tg = await send_telegram_message(text)
            summary["notification"] = tg
        except Exception as exc:
            summary["notification_error"] = str(exc)

    return summary
