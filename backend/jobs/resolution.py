"""
Resolution tracking — close paper trades whose markets have resolved.

For each open paper trade, re-fetch the market from Polymarket (resolved markets
drop out of the normal active-only sync), read the final outcome, and close the
trade with realized P&L. No real funds are involved.

    realized_pnl = simulated_shares * exit_probability - stake_usd
      exit_probability = 1.0 if the bet side won, else 0.0
"""

from typing import Any

from backend.collectors.polymarket import fetch_market_status, parse_resolution
from backend.db.paper_portfolio import (
    close_paper_trade,
    list_open_trades_for_resolution,
)


async def resolve_open_trades() -> dict[str, Any]:
    """
    Check every open paper trade for resolution and close the ones that resolved.

    Returns a summary: how many were checked, how many resolved, win/loss counts,
    the realized-P&L delta from this run, and per-trade details.
    """
    open_trades = list_open_trades_for_resolution()

    resolved: list[dict[str, Any]] = []
    wins = 0
    losses = 0
    realized_delta = 0.0

    for trade in open_trades:
        market = await fetch_market_status(str(trade["polymarket_id"]))
        winner = parse_resolution(market)
        if winner is None:
            continue  # still open / voided / not cleanly resolved

        side = trade["side"]
        won = side == winner
        shares = float(trade["simulated_shares"])
        stake = float(trade["stake_usd"])
        exit_probability = 1.0 if won else 0.0
        realized_pnl = round(shares * exit_probability - stake, 4)

        closed = close_paper_trade(trade["id"], exit_probability, realized_pnl)
        if not closed:
            continue

        realized_delta += realized_pnl
        if won:
            wins += 1
        else:
            losses += 1
        resolved.append({
            "trade_id": trade["id"],
            "market_id": trade["market_id"],
            "side": side,
            "winner": winner,
            "won": won,
            "realized_pnl": realized_pnl,
        })

    return {
        "checked": len(open_trades),
        "resolved": len(resolved),
        "wins": wins,
        "losses": losses,
        "realized_pnl_delta": round(realized_delta, 4),
        "details": resolved,
    }
