#!/usr/bin/env bash
# reset_experiment_data.sh — Wipe accumulated experiment OUTPUT for a clean run.
#
# Truncates: consensus_decisions, agent_runs, paper_trades, experiment_metrics
# Keeps:     markets, market_snapshots (reference data — re-synced each cycle)
#
# Use this to start the one-week paper-trading run with a clean slate, e.g. to
# drop pre-fix decisions whose markets are now permanently filtered (live sports
# finals, GTA proxies) and would otherwise linger forever in top/bottom-edges.
#
# No real funds are involved — this only clears simulation/analytics tables.

set -euo pipefail

CONTAINER="${PG_CONTAINER:-polymarket_postgres}"
DB_USER="${PG_USER:-polymarket_user}"
DB_NAME="${PG_DB:-polymarket_ai_desk}"

echo "This will DELETE all rows from:"
echo "  - consensus_decisions"
echo "  - agent_runs"
echo "  - paper_trades"
echo "  - experiment_metrics"
echo "markets and market_snapshots are kept."
echo ""
read -r -p "Type 'reset' to confirm: " CONFIRM

if [[ "$CONFIRM" != "reset" ]]; then
    echo "Aborted."
    exit 0
fi

docker exec -i "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 <<'SQL'
TRUNCATE TABLE paper_trades, consensus_decisions, agent_runs, experiment_metrics
    RESTART IDENTITY CASCADE;
SQL

echo ""
echo "Done. Experiment output tables are empty. markets/snapshots preserved."
