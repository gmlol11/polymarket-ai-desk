"""
Paper portfolio simulation — no real funds are used.
Only BET decisions create paper trades with a fixed stake (default $1.00).
"""

from typing import Any

from backend.db.connection import get_connection

DEFAULT_STAKE_USD = 1.0


def create_paper_trade_from_decision(
    decision: dict[str, Any],
    stake_usd: float = DEFAULT_STAKE_USD,
) -> dict[str, Any] | None:
    """
    Creates a paper trade for a BET decision.
    Returns the created trade dict or None if decision is not BET.

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
