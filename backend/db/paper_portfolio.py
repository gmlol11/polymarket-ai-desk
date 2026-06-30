"""
Paper portfolio simulation — no real funds are used.
Only BET decisions create paper trades with a fixed stake.

No wallet, no private key, no real money.
"""

from datetime import datetime, timezone
from typing import Any

from backend.config import PAPER_TRADE_STAKE_USD
from backend.db.connection import get_connection

DEFAULT_STAKE_USD: float = PAPER_TRADE_STAKE_USD


def create_paper_trade_from_decision(
    decision: dict[str, Any],
    stake_usd: float = DEFAULT_STAKE_USD,
) -> dict[str, Any] | None:
    """
    Creates a paper trade for a BET decision.
    Returns the created trade dict, or None if:
      - the decision is not BET, or
      - the entry probability is non-positive, or
      - the market already has an open paper trade (dedup — one position per
        market, so a recurring conviction re-bet every cooldown cycle doesn't
        accumulate duplicate exposure to the same outcome).

    Expected fields in `decision`:
      - id: consensus_decisions.id (DB row id)
      - market_id
      - market_probability
      - recommended_side ("YES" | "NO")
      - decision ("BET" | ...)
    """
    if decision.get("decision") != "BET":
        return None

    market_id = decision.get("market_id")
    consensus_decision_id = decision.get("id")
    side = decision.get("recommended_side")
    market_prob = float(decision.get("market_probability") or 0)

    if side == "YES":
        entry_probability = round(market_prob, 4)
    else:
        entry_probability = round(1.0 - market_prob, 4)

    if entry_probability <= 0:
        return None

    simulated_shares = round(stake_usd / entry_probability, 6)

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Dedup: skip if an open position already exists for this market.
            # Checked in the same transaction as the insert to avoid a race.
            cur.execute(
                "SELECT 1 FROM paper_trades "
                "WHERE market_id = %s AND status = 'open' LIMIT 1",
                (market_id,),
            )
            if cur.fetchone() is not None:
                return None

            cur.execute(
                """
                INSERT INTO paper_trades
                    (consensus_decision_id, market_id, side,
                     entry_probability, stake_usd, simulated_shares, status)
                VALUES (%s, %s, %s, %s, %s, %s, 'open')
                RETURNING id, consensus_decision_id, market_id, side,
                          entry_probability, stake_usd, simulated_shares,
                          status, opened_at
                """,
                (
                    consensus_decision_id,
                    market_id,
                    side,
                    entry_probability,
                    stake_usd,
                    simulated_shares,
                ),
            )
            columns = [desc[0] for desc in cur.description]
            row = cur.fetchone()
        conn.commit()

    return dict(zip(columns, row))


def list_paper_trades(limit: int = 20) -> list[dict[str, Any]]:
    limit = min(limit, 100)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    pt.id, pt.consensus_decision_id, pt.market_id,
                    m.question,
                    pt.side, pt.entry_probability, pt.stake_usd,
                    pt.simulated_shares, pt.status,
                    pt.exit_probability, pt.realized_pnl,
                    pt.opened_at, pt.closed_at
                FROM paper_trades pt
                LEFT JOIN markets m ON m.id = pt.market_id
                ORDER BY pt.opened_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]


def mark_open_trades() -> list[dict[str, Any]]:
    """
    For every open paper trade, fetch the latest market snapshot price,
    compute unrealized_pnl, and persist the values.

    Returns the list of updated trade records.
    No trades are closed here — this is purely mark-to-market.

    Requires migration 004_paper_mark_to_market.sql to have been applied.
    """
    now = datetime.now(timezone.utc)

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Open trades with current market snapshot
            cur.execute(
                """
                SELECT
                    pt.id,
                    pt.market_id,
                    pt.side,
                    pt.entry_probability,
                    pt.simulated_shares,
                    s.yes_price AS current_yes_price
                FROM paper_trades pt
                LEFT JOIN LATERAL (
                    SELECT yes_price
                    FROM market_snapshots
                    WHERE market_id = pt.market_id
                    ORDER BY created_at DESC
                    LIMIT 1
                ) s ON TRUE
                WHERE pt.status = 'open'
                """
            )
            open_cols = [desc[0] for desc in cur.description]
            open_trades = [dict(zip(open_cols, r)) for r in cur.fetchall()]

            updated: list[dict[str, Any]] = []
            for trade in open_trades:
                current_yes = trade.get("current_yes_price")
                if current_yes is None:
                    continue  # no snapshot yet — skip silently

                current_yes = float(current_yes)
                side = trade["side"]
                entry_prob = float(trade["entry_probability"])
                shares = float(trade["simulated_shares"])

                # Current trade probability: YES price for YES bets, NO price for NO bets
                current_prob = current_yes if side == "YES" else (1.0 - current_yes)
                unrealized_pnl = round((current_prob - entry_prob) * shares, 4)

                cur.execute(
                    """
                    UPDATE paper_trades
                    SET current_probability = %s,
                        unrealized_pnl      = %s,
                        last_marked_at      = %s
                    WHERE id = %s
                    RETURNING id, market_id, side, entry_probability,
                              current_probability, unrealized_pnl,
                              stake_usd, status, last_marked_at
                    """,
                    (round(current_prob, 4), unrealized_pnl, now, trade["id"]),
                )
                ret_cols = [desc[0] for desc in cur.description]
                row = cur.fetchone()
                if row:
                    updated.append(dict(zip(ret_cols, row)))

        conn.commit()

    return updated


def get_paper_summary() -> dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*)                            AS total_trades,
                    COUNT(*) FILTER (WHERE status = 'open')   AS open_trades,
                    COUNT(*) FILTER (WHERE status = 'closed') AS closed_trades,
                    COALESCE(SUM(stake_usd), 0)         AS total_stake_usd,
                    COALESCE(SUM(simulated_shares), 0)  AS total_simulated_shares,
                    COALESCE(SUM(realized_pnl), 0)      AS realized_pnl,
                    COUNT(*) FILTER (WHERE side = 'YES') AS yes_trades,
                    COUNT(*) FILTER (WHERE side = 'NO')  AS no_trades
                FROM paper_trades
                """
            )
            columns = [desc[0] for desc in cur.description]
            row = cur.fetchone()

    return dict(zip(columns, row))
