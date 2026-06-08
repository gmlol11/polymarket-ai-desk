"""
Decision analytics — aggregations over consensus_decisions.
"""

from typing import Any

from backend.db.connection import get_connection


def get_recently_analyzed_market_ids(hours: int) -> set[int]:
    """
    Return the set of market_ids that have at least one consensus_decision
    created within the last `hours` hours.
    Used by the runner to skip re-analysis during the cooldown window.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT market_id
                FROM consensus_decisions
                WHERE created_at >= NOW() - (%s * INTERVAL '1 hour')
                """,
                (hours,),
            )
            return {row[0] for row in cur.fetchall()}


def get_decision_summary() -> dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*)                                            AS total_decisions,
                    COUNT(*) FILTER (WHERE decision = 'BET')           AS bet_count,
                    COUNT(*) FILTER (WHERE decision = 'WATCH')         AS watch_count,
                    COUNT(*) FILTER (WHERE decision = 'SKIP')          AS skip_count,
                    COUNT(*) FILTER (WHERE decision = 'NEEDS_MORE_RESEARCH')
                                                                       AS needs_more_research_count,
                    COUNT(*) FILTER (WHERE recommended_side = 'YES')   AS yes_count,
                    COUNT(*) FILTER (WHERE recommended_side = 'NO')    AS no_count,
                    ROUND(AVG(edge)::NUMERIC, 4)                       AS avg_edge,
                    ROUND(MAX(edge)::NUMERIC, 4)                       AS max_positive_edge,
                    ROUND(MIN(edge)::NUMERIC, 4)                       AS max_negative_edge,
                    ROUND(AVG(confidence)::NUMERIC, 4)                 AS avg_confidence
                FROM consensus_decisions
                """
            )
            columns = [desc[0] for desc in cur.description]
            row = cur.fetchone()
            summary = dict(zip(columns, row))

            cur.execute(
                """
                SELECT
                    COUNT(*)                                      AS total_paper_trades,
                    COUNT(*) FILTER (WHERE status = 'open')      AS open_paper_trades
                FROM paper_trades
                """
            )
            columns = [desc[0] for desc in cur.description]
            paper_row = cur.fetchone()
            summary.update(dict(zip(columns, paper_row)))

    return summary


def get_near_bets(limit: int = 20) -> list[dict[str, Any]]:
    """
    Decisions that almost qualified as BET:
    - Positive edge but below threshold (0 < edge < 0.05)
    - Good edge but confidence too low (edge >= 0.05 AND confidence < 0.65)
    - NEEDS_MORE_RESEARCH with edge >= 0.05 (likely blocked by sides disagreement)
    """
    limit = min(limit, 100)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    cd.id, cd.market_id, m.question,
                    cd.market_probability, cd.consensus_probability,
                    cd.edge, cd.confidence,
                    cd.recommended_side, cd.decision, cd.reason,
                    cd.created_at
                FROM consensus_decisions cd
                LEFT JOIN markets m ON m.id = cd.market_id
                WHERE cd.decision != 'BET'
                  AND (
                      (cd.edge > 0 AND cd.edge < 0.05)
                      OR (cd.edge >= 0.05 AND cd.confidence < 0.65)
                      OR (cd.decision = 'NEEDS_MORE_RESEARCH' AND cd.edge >= 0.05)
                  )
                ORDER BY cd.created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]


def get_strong_negative_edge(limit: int = 20) -> list[dict[str, Any]]:
    """
    Decisions with edge <= -0.05, ordered by most negative edge first.
    These are markets where both agents think the market is significantly overpriced.
    """
    limit = min(limit, 100)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    cd.id, cd.market_id, m.question,
                    cd.market_probability, cd.consensus_probability,
                    cd.edge, cd.confidence,
                    cd.recommended_side, cd.decision, cd.reason,
                    cd.created_at
                FROM consensus_decisions cd
                LEFT JOIN markets m ON m.id = cd.market_id
                WHERE cd.edge <= -0.05
                ORDER BY cd.edge ASC
                LIMIT %s
                """,
                (limit,),
            )
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Latest-decision-per-market helpers
# All three share the same CTE that picks the most recent decision per market,
# then differ only in the outer ORDER BY.
# ---------------------------------------------------------------------------

_LATEST_BY_MARKET_CTE = """
WITH latest AS (
    SELECT DISTINCT ON (cd.market_id)
        cd.id,
        cd.market_id,
        m.polymarket_id,
        m.question,
        cd.market_probability,
        cd.consensus_probability,
        cd.edge,
        cd.confidence,
        cd.recommended_side,
        cd.decision,
        cd.reason,
        cd.created_at
    FROM consensus_decisions cd
    LEFT JOIN markets m ON m.id = cd.market_id
    ORDER BY cd.market_id, cd.created_at DESC
)
"""


def _run_latest_query(order_by: str, limit: int) -> list[dict[str, Any]]:
    limit = min(limit, 100)
    sql = _LATEST_BY_MARKET_CTE + f"SELECT * FROM latest ORDER BY {order_by} LIMIT %s"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (limit,))
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]


def get_latest_by_market(limit: int = 20) -> list[dict[str, Any]]:
    """Latest consensus decision per market, ordered by most recently analyzed first."""
    return _run_latest_query("created_at DESC", limit)


def get_top_edges(limit: int = 20) -> list[dict[str, Any]]:
    """Latest decision per market, ordered by highest edge first (best value bets)."""
    return _run_latest_query("edge DESC", limit)


def get_bottom_edges(limit: int = 20) -> list[dict[str, Any]]:
    """Latest decision per market, ordered by lowest edge first (most overpriced markets)."""
    return _run_latest_query("edge ASC", limit)


# ---------------------------------------------------------------------------
# Weekly paper-trading report
# ---------------------------------------------------------------------------

def get_paper_weekly_report(days: int = 7) -> dict[str, Any]:
    """
    Aggregate consensus decisions and paper trades from the last `days` days.

    Market resolution / close-out tracking is not yet implemented.
    `realized_pnl` reflects only manually-closed trades (rare at this stage).
    `unrealized_pnl` is populated by POST /paper/mark-to-market.

    The response always includes "resolution_tracking": "not_implemented_yet"
    as an explicit reminder.
    """
    days = min(max(days, 1), 365)

    with get_connection() as conn:
        with conn.cursor() as cur:

            # ── Decision aggregates ────────────────────────────────────────
            cur.execute(
                """
                SELECT
                    COUNT(*)                                            AS consensus_decisions_count,
                    COUNT(DISTINCT market_id)                          AS unique_markets_count,
                    COUNT(*) FILTER (WHERE decision = 'BET')           AS bet_count,
                    COUNT(*) FILTER (WHERE decision = 'WATCH')         AS watch_count,
                    COUNT(*) FILTER (WHERE decision = 'SKIP')          AS skip_count,
                    COUNT(*) FILTER (WHERE decision = 'NEEDS_MORE_RESEARCH')
                                                                       AS needs_more_research_count,
                    COUNT(*) FILTER (WHERE recommended_side = 'YES')   AS yes_count,
                    COUNT(*) FILTER (WHERE recommended_side = 'NO')    AS no_count,
                    ROUND(AVG(edge)::NUMERIC, 4)                       AS avg_edge,
                    ROUND(MAX(edge)::NUMERIC, 4)                       AS max_positive_edge,
                    ROUND(MIN(edge)::NUMERIC, 4)                       AS max_negative_edge
                FROM consensus_decisions
                WHERE created_at >= NOW() - (%s * INTERVAL '1 day')
                """,
                (days,),
            )
            cols = [desc[0] for desc in cur.description]
            row = cur.fetchone()
            report: dict[str, Any] = dict(zip(cols, row))
            report["period_days"] = days
            report["decision_counts"] = {
                "BET": report.pop("bet_count"),
                "WATCH": report.pop("watch_count"),
                "SKIP": report.pop("skip_count"),
                "NEEDS_MORE_RESEARCH": report.pop("needs_more_research_count"),
            }
            report["recommended_side_counts"] = {
                "YES": report.pop("yes_count"),
                "NO": report.pop("no_count"),
            }

            # ── Category breakdown (uses stored category_guess, migration 005) ──
            try:
                cur.execute(
                    """
                    SELECT COALESCE(category_guess, 'unknown') AS category,
                           COUNT(*) AS n,
                           COUNT(*) FILTER (WHERE decision = 'BET') AS bet
                    FROM consensus_decisions
                    WHERE created_at >= NOW() - (%s * INTERVAL '1 day')
                    GROUP BY 1
                    ORDER BY n DESC
                    """,
                    (days,),
                )
                report["category_breakdown"] = [
                    {"category": r[0], "decisions": r[1], "bets": r[2]}
                    for r in cur.fetchall()
                ]
            except Exception:
                conn.rollback()
                report["category_breakdown"] = "unavailable_apply_migration_005"

            # ── Paper trade aggregates ─────────────────────────────────────
            cur.execute(
                """
                SELECT
                    COUNT(*)                                            AS paper_trades_count,
                    COUNT(*) FILTER (WHERE status = 'open')            AS open_paper_trades,
                    COUNT(*) FILTER (WHERE status = 'closed')          AS closed_paper_trades,
                    COALESCE(SUM(stake_usd), 0)                        AS total_stake_usd,
                    COALESCE(SUM(realized_pnl), 0)                     AS realized_pnl
                FROM paper_trades
                WHERE opened_at >= NOW() - (%s * INTERVAL '1 day')
                """,
                (days,),
            )
            cols = [desc[0] for desc in cur.description]
            paper_row = cur.fetchone()
            report.update(dict(zip(cols, paper_row)))

            # ── Best paper trade (highest unrealized or realized pnl) ─────
            _trade_select = """
                SELECT
                    pt.id, pt.market_id, m.question,
                    pt.side, pt.entry_probability, pt.stake_usd,
                    pt.simulated_shares, pt.status,
                    pt.current_probability, pt.unrealized_pnl,
                    pt.realized_pnl, pt.opened_at
                FROM paper_trades pt
                LEFT JOIN markets m ON m.id = pt.market_id
                WHERE pt.opened_at >= NOW() - (%s * INTERVAL '1 day')
            """
            _trade_cols_cached: list[str] | None = None

            cur.execute(
                _trade_select + " ORDER BY COALESCE(pt.unrealized_pnl, pt.realized_pnl, 0) DESC LIMIT 1",
                (days,),
            )
            _trade_cols_cached = [desc[0] for desc in cur.description]
            best_row = cur.fetchone()
            report["best_paper_trade"] = (
                dict(zip(_trade_cols_cached, best_row)) if best_row else None
            )

            cur.execute(
                _trade_select + " ORDER BY COALESCE(pt.unrealized_pnl, pt.realized_pnl, 0) ASC LIMIT 1",
                (days,),
            )
            worst_row = cur.fetchone()
            report["worst_paper_trade"] = (
                dict(zip(_trade_cols_cached, worst_row)) if worst_row else None
            )

            # ── Top/bottom edges within period (latest per market) ─────────
            _period_cte = """
                WITH latest AS (
                    SELECT DISTINCT ON (cd.market_id)
                        cd.market_id, m.question,
                        cd.consensus_probability, cd.edge, cd.confidence,
                        cd.recommended_side, cd.decision, cd.created_at
                    FROM consensus_decisions cd
                    LEFT JOIN markets m ON m.id = cd.market_id
                    WHERE cd.created_at >= NOW() - (%s * INTERVAL '1 day')
                    ORDER BY cd.market_id, cd.created_at DESC
                )
            """

            cur.execute(_period_cte + "SELECT * FROM latest ORDER BY edge DESC LIMIT 5", (days,))
            edge_cols = [desc[0] for desc in cur.description]
            report["latest_top_edges"] = [
                dict(zip(edge_cols, r)) for r in cur.fetchall()
            ]

            cur.execute(_period_cte + "SELECT * FROM latest ORDER BY edge ASC LIMIT 5", (days,))
            report["latest_bottom_edges"] = [
                dict(zip(edge_cols, r)) for r in cur.fetchall()
            ]

            report["resolution_tracking"] = "not_implemented_yet"

    return report
