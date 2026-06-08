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

The runner syncs up to 50 markets from Polymarket, picks up to 3 modelable
candidates, runs the full agent pipeline, and saves results to `agent_runs`
and `consensus_decisions`.

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
