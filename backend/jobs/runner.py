"""
Experiment runner — executes one full pipeline cycle:
  sync markets → score → research → cooldown filter → diverse select
  → claude analyst → openai challenger → consensus → persist

Configuration is read from backend/config.py (environment variables with safe defaults).
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from agents.claude_analyst import analyze_markets
from agents.consensus_agent import run_consensus
from agents.openai_challenger import challenge_markets
from agents.research_agent import research_markets
from agents.simple_filter import score_markets, select_diverse_candidates
from backend.collectors.polymarket import sync_markets
from backend.config import (
    ANALYST_FAILURE_ALERT_RATIO,
    EXPERIMENT_MARKET_LIMIT,
    EXPERIMENT_MIN_DAYS_TO_RESOLUTION,
    EXPERIMENT_REANALYZE_COOLDOWN_HOURS,
    EXPERIMENT_SYNC_LIMIT,
    PAPER_TRADE_STAKE_USD,
)
from backend.db.agent_history import save_agent_run, save_consensus_decision
from backend.db.analytics import get_recently_analyzed_market_ids
from backend.db.paper_portfolio import (
    create_paper_trade_from_decision,
    get_portfolio_state,
    mark_open_trades,
)
from backend.jobs.resolution import resolve_open_trades
from backend.notifications.telegram import format_experiment_summary, send_telegram_message
from backend.scanner import get_candidates


async def _refresh_portfolio() -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Run every cycle, independent of whether new markets were analyzed:
    resolve any settled trades, mark the rest to market, return (resolution,
    portfolio_state). Each step is best-effort so a failure can't abort the run.
    """
    try:
        resolution = await resolve_open_trades()
    except Exception as exc:
        resolution = {"error": str(exc)}
    try:
        mark_open_trades()
    except Exception:
        pass
    try:
        portfolio = get_portfolio_state()
    except Exception as exc:
        portfolio = {"error": str(exc)}
    return resolution, portfolio


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
    _min_days = EXPERIMENT_MIN_DAYS_TO_RESOLUTION
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

    # 3b. Resolution-proximity guardrail: drop markets resolving within _min_days.
    #     Live / imminent events (e.g. an in-progress sports final) carry market
    #     information the AI agents cannot see; the model's disagreement there is
    #     ignorance, not edge. Markets with no end_date are kept (can't assess).
    skipped_imminent_ids: list[int] = []
    if _min_days > 0:
        cutoff = datetime.now(timezone.utc) + timedelta(days=_min_days)
        kept = []
        for m in eligible:
            end_date = m.get("end_date")
            if end_date is not None:
                ed = end_date if end_date.tzinfo else end_date.replace(tzinfo=timezone.utc)
                if ed <= cutoff:
                    skipped_imminent_ids.append(m["id"])
                    continue
            kept.append(m)
        eligible = kept

    # 4. Cooldown: skip markets analyzed within the cooldown window
    recent_ids = get_recently_analyzed_market_ids(_cooldown_hours)
    skipped_recent_ids = [m["id"] for m in eligible if m["id"] in recent_ids]
    fresh = [m for m in eligible if m["id"] not in recent_ids]

    # 5. Diverse selection (round-robin by category_guess)
    selected = select_diverse_candidates(fresh, _market_limit)

    if not selected:
        resolution, portfolio = await _refresh_portfolio()
        finished_at = datetime.now(timezone.utc)
        summary: dict[str, Any] = {
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "duration_seconds": round((finished_at - started_at).total_seconds(), 1),
            "sync_limit": _sync_limit,
            "requested_market_limit": _market_limit,
            "cooldown_hours": _cooldown_hours,
            "min_days_to_resolution": _min_days,
            "sync": sync_result,
            "markets_analyzed": 0,
            "analyzed_market_ids": [],
            "skipped_recent_market_ids": skipped_recent_ids,
            "skipped_imminent_market_ids": skipped_imminent_ids,
            "decisions": [],
            "paper_trades_opened": 0,
            "resolution": resolution,
            "portfolio": portfolio,
            "status": "no_markets",
        }
        if notify:
            try:
                text = format_experiment_summary(summary)
                tg = await send_telegram_message(text)
                summary["notification"] = tg
            except Exception as exc:
                summary["notification_error"] = repr(exc)
        return summary

    # 6. Full agent pipeline
    with_analyst = analyze_markets(selected)
    with_challenger = challenge_markets(with_analyst)
    results = run_consensus(with_challenger)

    # 7. Persist and build decision list
    decisions: list[dict[str, Any]] = []
    paper_trades_opened = 0
    analyst_failures = 0
    analyst_error_sample: str | None = None

    for item in results:
        market_id = item["id"]
        analyst = item.get("analyst") or {}
        challenger = item.get("challenger") or {}
        consensus = item.get("consensus") or {}

        if "error" in analyst:
            analyst_failures += 1
            if analyst_error_sample is None:
                analyst_error_sample = str(analyst.get("error"))[:200]

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

    # Resolve settled trades, mark the rest, snapshot the portfolio.
    resolution, portfolio = await _refresh_portfolio()

    finished_at = datetime.now(timezone.utc)

    # Degradation check: a cycle where most analyst calls failed still
    # "completes", but produced no real analysis (e.g. exhausted API credits).
    # Flag it loudly instead of reporting a misleading "ok".
    analyzed = len(decisions)
    degraded = analyzed > 0 and (analyst_failures / analyzed) >= ANALYST_FAILURE_ALERT_RATIO

    summary = {
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": round((finished_at - started_at).total_seconds(), 1),
        "sync_limit": _sync_limit,
        "requested_market_limit": _market_limit,
        "cooldown_hours": _cooldown_hours,
        "min_days_to_resolution": _min_days,
        "sync": sync_result,
        "markets_analyzed": analyzed,
        "analyzed_market_ids": [d["market_id"] for d in decisions],
        "skipped_recent_market_ids": skipped_recent_ids,
        "skipped_imminent_market_ids": skipped_imminent_ids,
        "decisions": decisions,
        "paper_trades_opened": paper_trades_opened,
        "analyst_failures": analyst_failures,
        "analyst_error_sample": analyst_error_sample,
        "resolution": resolution,
        "portfolio": portfolio,
        "status": "degraded" if degraded else "ok",
    }

    if notify:
        try:
            text = format_experiment_summary(summary)
            tg = await send_telegram_message(text)
            summary["notification"] = tg
        except Exception as exc:
            summary["notification_error"] = str(exc)

    return summary
