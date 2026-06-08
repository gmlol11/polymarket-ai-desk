"""
Decision analytics — aggregations over consensus_decisions.
"""

from typing import Any

from backend.db.connection import get_connection


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
