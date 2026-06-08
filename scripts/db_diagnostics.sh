#!/usr/bin/env bash
# db_diagnostics.sh — Read-only health check of the experiment database.
# Prints decision distribution, edge stats by side, top markets by |edge|,
# price-plausibility sample, and category coverage.
#
# Usage: bash scripts/db_diagnostics.sh
# Requires the Postgres docker container to be running.

set -euo pipefail

CONTAINER="${PG_CONTAINER:-polymarket_postgres}"
DB_USER="${PG_USER:-polymarket_user}"
DB_NAME="${PG_DB:-polymarket_ai_desk}"

psql_q() {
    docker exec -i "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -P pager=off "$@"
}

echo "============================================================"
echo " Polymarket AI Desk — DB diagnostics"
echo " container=$CONTAINER db=$DB_NAME"
echo "============================================================"

echo ""
echo "── Row counts ──────────────────────────────────────────────"
psql_q -c "
SELECT 'markets'             AS table, COUNT(*) FROM markets
UNION ALL SELECT 'market_snapshots', COUNT(*) FROM market_snapshots
UNION ALL SELECT 'agent_runs',       COUNT(*) FROM agent_runs
UNION ALL SELECT 'consensus_decisions', COUNT(*) FROM consensus_decisions
UNION ALL SELECT 'paper_trades',     COUNT(*) FROM paper_trades;
"

echo ""
echo "── Decision distribution ───────────────────────────────────"
psql_q -c "
SELECT decision, COUNT(*) AS n
FROM consensus_decisions
GROUP BY decision
ORDER BY n DESC;
"

echo ""
echo "── Edge stats by recommended side ──────────────────────────"
echo " (healthy: NO side should have POSITIVE max_edge after the fix)"
psql_q -c "
SELECT
    recommended_side AS side,
    COUNT(*)                 AS n,
    ROUND(AVG(edge), 3)      AS avg_edge,
    ROUND(MIN(edge), 3)      AS min_edge,
    ROUND(MAX(edge), 3)      AS max_edge,
    ROUND(AVG(confidence),3) AS avg_conf
FROM consensus_decisions
GROUP BY recommended_side
ORDER BY side;
"

echo ""
echo "── Top 10 markets by |edge| (latest decision per market) ───"
psql_q -c "
WITH latest AS (
    SELECT DISTINCT ON (cd.market_id)
        cd.market_id, m.question,
        cd.market_probability AS mkt, cd.consensus_probability AS model,
        cd.edge, cd.recommended_side AS side, cd.decision
    FROM consensus_decisions cd
    LEFT JOIN markets m ON m.id = cd.market_id
    ORDER BY cd.market_id, cd.created_at DESC
)
SELECT LEFT(question, 48) AS question, mkt, model, edge, side, decision
FROM latest
ORDER BY ABS(edge) DESC
LIMIT 10;
"

echo ""
echo "── Price plausibility: markets with very high yes_price ────"
echo " (yes_price > 0.7 on single-outcome titles often = live event)"
psql_q -c "
WITH latest_snap AS (
    SELECT DISTINCT ON (s.market_id)
        s.market_id, s.yes_price, s.liquidity
    FROM market_snapshots s
    ORDER BY s.market_id, s.created_at DESC
)
SELECT LEFT(m.question, 50) AS question,
       ls.yes_price, m.end_date::date AS resolves
FROM latest_snap ls
JOIN markets m ON m.id = ls.market_id
WHERE ls.yes_price > 0.7
ORDER BY ls.yes_price DESC
LIMIT 10;
"

echo ""
echo "── Analyzed category coverage (diversity check) ────────────"
psql_q -c "
SELECT COALESCE(NULLIF(m.category, ''), 'unknown') AS category, COUNT(*) AS decisions
FROM consensus_decisions cd
LEFT JOIN markets m ON m.id = cd.market_id
GROUP BY 1
ORDER BY decisions DESC;
"

echo ""
echo "── Paper trades summary ────────────────────────────────────"
psql_q -c "
SELECT
    COUNT(*)                                   AS total,
    COUNT(*) FILTER (WHERE status='open')      AS open,
    COUNT(*) FILTER (WHERE status='closed')    AS closed,
    COALESCE(SUM(stake_usd),0)                 AS staked_usd,
    COALESCE(SUM(unrealized_pnl),0)            AS unrealized_pnl,
    COALESCE(SUM(realized_pnl),0)              AS realized_pnl
FROM paper_trades;
"

echo ""
echo "Done."
