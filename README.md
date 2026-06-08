# Polymarket AI Desk

Multi-agent pipeline for analyzing Polymarket prediction markets.

## Stack

- **Backend**: FastAPI + psycopg3 + Redis
- **Agents**: Claude (analyst) + OpenAI (challenger) + rule-based consensus
- **Storage**: PostgreSQL 16

## Setup

```bash
# 1. Start infrastructure
docker compose up -d

# 2. Apply DB migrations
docker exec -i polymarket_postgres psql -U polymarket_user -d polymarket_ai_desk < database/001_init.sql
docker exec -i polymarket_postgres psql -U polymarket_user -d polymarket_ai_desk < database/002_agent_history.sql

# 3. Create virtualenv and install deps
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt

# 4. Configure env
cp .env.example .env
# edit .env and fill in ANTHROPIC_API_KEY and OPENAI_API_KEY

# 5. Start server
python -m uvicorn backend.app:app --reload --reload-exclude '.venv' --host 0.0.0.0 --port 8000
```

## Usage

```bash
# Sync markets from Polymarket
curl -X POST "http://127.0.0.1:8000/markets/sync?limit=20"

# Run full pipeline for 1 market (analyst + challenger + consensus)
curl "http://127.0.0.1:8000/agents/consensus?limit=1" | python3 -m json.tool

# View persisted consensus decisions
curl "http://127.0.0.1:8000/consensus-decisions?limit=20" | python3 -m json.tool

# View all agent runs
curl "http://127.0.0.1:8000/agent-runs?limit=20" | python3 -m json.tool

# View history for a specific market
curl "http://127.0.0.1:8000/markets/20/agent-history" | python3 -m json.tool
```

## Pipeline

```
Collector → Scanner → Simple Filter → Research Agent
                                           ↓
                                    Claude Analyst
                                           ↓
                                   OpenAI Challenger
                                           ↓
                                    Consensus Agent → DB
```

## Experiment Runner

Run one full cycle manually (sync + score + analyze up to 3 markets + persist):

```bash
curl -X POST "http://127.0.0.1:8000/jobs/run-once" | python3 -m json.tool
```

Run cycle with Telegram notification:

```bash
curl -X POST "http://127.0.0.1:8000/jobs/run-once-notify" | python3 -m json.tool
```

## Paper Portfolio

No real funds are used. Paper trading simulates what would happen if every
BET decision was followed with a fixed stake.

- Default stake: **$1.00 per trade**
- Only `BET` decisions create trades
- `entry_probability` = market price for YES trades, `1 - market_price` for NO trades
- `simulated_shares = stake / entry_probability`
- Trades start with `status = "open"` (closing/PnL tracking is a future feature)

```bash
# List paper trades
curl "http://127.0.0.1:8000/paper/trades" | python3 -m json.tool

# Portfolio summary
curl "http://127.0.0.1:8000/paper/summary" | python3 -m json.tool
```

## Analytics

```bash
# Overall decision stats (counts, avg edge, avg confidence, paper trades)
curl "http://127.0.0.1:8000/analytics/decision-summary" | python3 -m json.tool

# Decisions that almost qualified as BET (positive edge below threshold,
# or good edge but low confidence, or sides disagreement blocked BET)
curl "http://127.0.0.1:8000/analytics/near-bets?limit=20" | python3 -m json.tool

# Markets where both agents strongly disagreed with the price (edge <= -5%)
curl "http://127.0.0.1:8000/analytics/strong-negative-edge?limit=20" | python3 -m json.tool

# Latest decision per market — deduplicates history noise, sorted newest first
curl "http://127.0.0.1:8000/analytics/latest-by-market?limit=20" | python3 -m json.tool

# Latest decision per market, sorted by highest edge first (best value opportunities)
curl "http://127.0.0.1:8000/analytics/top-edges?limit=20" | python3 -m json.tool

# Latest decision per market, sorted by lowest edge first (most overpriced markets)
curl "http://127.0.0.1:8000/analytics/bottom-edges?limit=20" | python3 -m json.tool
```

## Telegram Notifications

### Setup

1. Open [@BotFather](https://t.me/BotFather) in Telegram, send `/newbot`, follow prompts
2. Copy the token BotFather gives you → `TELEGRAM_BOT_TOKEN`
3. Start a chat with your bot (or add it to a group)
4. Get your `chat_id`:
   ```bash
   curl "https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates"
   ```
   Find `"chat": {"id": ...}` in the response
5. Add to `.env`:
   ```
   TELEGRAM_BOT_TOKEN=your_token_here
   TELEGRAM_CHAT_ID=your_chat_id_here
   ```

### Test notification

```bash
curl -X POST "http://127.0.0.1:8000/notifications/test"
```

### Run cycle with notification

```bash
curl -X POST "http://127.0.0.1:8000/jobs/run-once-notify" | python3 -m json.tool
```

Check runner status:

```bash
curl "http://127.0.0.1:8000/jobs/status" | python3 -m json.tool
```

The runner syncs up to `EXPERIMENT_SYNC_LIMIT` (default 500) markets from
Polymarket, skips markets analyzed within the cooldown window
(`EXPERIMENT_REANALYZE_COOLDOWN_HOURS`, default 48h), then picks up to
`EXPERIMENT_MARKET_LIMIT` (default 25) diverse candidates using round-robin
across market categories.

## One-week paper trading research run

### Daily sample defaults

| Setting | Default | Env var |
|---------|---------|---------|
| Markets synced per run | 500 | `EXPERIMENT_SYNC_LIMIT` |
| Markets analyzed per run | 25 | `EXPERIMENT_MARKET_LIMIT` |
| Re-analysis cooldown | 48h | `EXPERIMENT_REANALYZE_COOLDOWN_HOURS` |
| Resolution proximity skip | 3 days | `EXPERIMENT_MIN_DAYS_TO_RESOLUTION` |
| Paper trade stake (USD) | $1.00 | `PAPER_TRADE_STAKE_USD` |
| BET min edge | 5% | `BET_MIN_EDGE` |
| BET max plausible edge | 25% | `BET_MAX_EDGE` |
| BET min confidence | 65% | `BET_MIN_CONFIDENCE` |

### Autonomous-run guardrails

The pipeline is designed to accumulate *meaningful* paper-trading data without
supervision. Several guardrails prevent the AI agents from "trading" their own
blind spots:

- **Edge sign** — `NO`-side edge is `market_prob - consensus_prob` (a genuine
  overpriced-YES market produces a positive NO edge).
- **Max plausible edge** — an edge above `BET_MAX_EDGE` (25%) on a liquid market
  is almost never real. Such cases are flagged `NEEDS_MORE_RESEARCH` for review
  instead of becoming an automatic BET. (e.g. an in-progress sports final the
  model can't see, where the market is far better informed.)
- **Resolution proximity** — markets resolving within
  `EXPERIMENT_MIN_DAYS_TO_RESOLUTION` (3) days are skipped; live/imminent events
  carry information the model lacks.
- **Proxy markets** — "X before GTA VI"-style joke/proxy markets are forced to
  `skip` and marked non-modelable.
- **Sports gate** (`BET_EXCLUDE_SPORTS`, default on) — sports markets (live
  finals/cups) are priced off efficient real-time betting markets the AI can't
  see. A sports BET is downgraded to WATCH: still analyzed and counted in
  category analytics, but no paper trade is opened.
- **Cooldown** — a market analyzed within the last 48h is not re-analyzed.

### Inspect the database

```bash
# Read-only health check: decision distribution, edge by side,
# top markets by |edge|, price plausibility, category coverage
bash scripts/db_diagnostics.sh
```

### Start the week with a clean slate (optional)

Wipes accumulated decisions / agent runs / paper trades (keeps markets and
snapshots). Useful to drop pre-fix decisions whose markets are now permanently
filtered. Paper-only — no real funds involved.

```bash
bash scripts/reset_experiment_data.sh   # type 'reset' to confirm
```

### Run manually

```bash
# Single cycle with Telegram summary
curl -X POST "http://127.0.0.1:8000/jobs/run-once-notify" | python3 -m json.tool

# Quick test with smaller sample
curl -X POST "http://127.0.0.1:8000/jobs/run-once" | python3 -m json.tool
```

### Apply migrations (run once)

```bash
# Mark-to-market columns on paper_trades
docker exec -i polymarket_postgres psql -U polymarket_user -d polymarket_ai_desk \
    < database/004_paper_mark_to_market.sql

# category_guess on consensus_decisions (enables category breakdown in reports)
docker exec -i polymarket_postgres psql -U polymarket_user -d polymarket_ai_desk \
    < database/005_decision_category.sql
```

### Install launchd automation (macOS)

This sets up two LaunchAgents:
- **Backend keep-alive**: starts FastAPI on login, restarts on crash
- **Daily 10:00 experiment**: calls `/jobs/run-once-notify` every day

launchd owns the backend, so **stop any manually-started uvicorn first** —
otherwise the agent can't bind port 8000 and crash-loops.

```bash
# 1. Free port 8000 (kill any manual backend running old code)
bash scripts/stop_backend.sh

# 2. Install + bootstrap both agents (modern macOS: uses launchctl bootstrap)
bash scripts/install_launchd.sh

# 3. Verify the agent is up and serving the LATEST code
launchctl list | grep polymarket
curl -s http://127.0.0.1:8000/jobs/status | python3 -m json.tool

# 4. Fire the daily job once now (don't wait for 10:00)
launchctl kickstart -k gui/$(id -u)/com.polymarket-ai.daily-experiment
```

### Check logs

```bash
# Backend logs
tail -f logs/backend_stderr.log

# Daily experiment output
tail -f logs/daily_stdout.log

# Per-run experiment logs (timestamped)
ls logs/experiment_*.log
tail logs/experiment_$(ls logs/experiment_*.log | sort | tail -1 | xargs basename)
```

### Get weekly report

```bash
# Full 7-day report
curl "http://127.0.0.1:8000/analytics/paper-weekly-report?days=7" | python3 -m json.tool

# Mark open paper trades to current market prices first
curl -X POST "http://127.0.0.1:8000/paper/mark-to-market" | python3 -m json.tool

# Paper portfolio summary
curl "http://127.0.0.1:8000/paper/summary" | python3 -m json.tool

# Top/bottom edges (latest per market, deduped)
curl "http://127.0.0.1:8000/analytics/top-edges?limit=10" | python3 -m json.tool
curl "http://127.0.0.1:8000/analytics/bottom-edges?limit=10" | python3 -m json.tool
```

### Uninstall launchd

```bash
bash scripts/uninstall_launchd.sh
```

> **No real funds are used.** Paper trading only. No wallet, no private key.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /health | Liveness check |
| GET | /readyz | Readiness check (postgres + redis) |
| POST | /markets/sync | Sync markets from Polymarket API |
| GET | /markets | List markets with latest snapshot |
| GET | /markets/{id} | Market detail + snapshots |
| GET | /markets/{id}/agent-history | All agent runs and decisions for a market |
| GET | /scanner/candidates | Raw scanner output |
| GET | /agents/simple-filter | Scored + classified markets |
| GET | /agents/research | Research-enriched markets |
| GET | /agents/analyze | Claude analyst output (persisted) |
| GET | /agents/consensus | Full pipeline output (persisted) |
| GET | /agent-runs | Persisted agent run history |
| GET | /consensus-decisions | Persisted consensus decision history |
| POST | /jobs/run-once | Run one full experiment cycle manually |
| POST | /jobs/run-once-notify | Run cycle and send Telegram notification |
| GET | /jobs/status | Scheduler/runner status |
| POST | /notifications/test | Send test Telegram message |
| GET | /paper/trades | List simulated paper trades |
| GET | /paper/summary | Paper portfolio summary stats |
| POST | /paper/mark-to-market | Compute unrealized PnL from current snapshot prices |
| GET | /analytics/decision-summary | Aggregate decision stats |
| GET | /analytics/near-bets | Decisions close to BET threshold |
| GET | /analytics/strong-negative-edge | Decisions with edge ≤ -5% |
| GET | /analytics/latest-by-market | Latest decision per market, newest first |
| GET | /analytics/top-edges | Latest decision per market, best edge first |
| GET | /analytics/bottom-edges | Latest decision per market, worst edge first |
| GET | /analytics/paper-weekly-report | Full weekly paper-trading report |
