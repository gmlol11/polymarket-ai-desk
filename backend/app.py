import os

import psycopg
import redis
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException

from agents.claude_analyst import analyze_markets
from agents.consensus_agent import run_consensus
from agents.openai_challenger import challenge_markets
from agents.research_agent import research_markets
from agents.simple_filter import score_markets
from backend.collectors.polymarket import sync_markets
from backend.db.agent_history import (
    get_market_agent_history,
    list_agent_runs,
    list_consensus_decisions,
    save_agent_run,
    save_consensus_decision,
)
from backend.jobs.runner import run_experiment_cycle
from backend.notifications.telegram import send_telegram_message
from backend.scanner import get_candidates

load_dotenv()

app = FastAPI(title="Polymarket AI Desk")


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://polymarket_user:polymarket_password@localhost:5433/polymarket_ai_desk",
)

REDIS_URL = os.getenv(
    "REDIS_URL",
    "redis://localhost:6380/0",
)


def db_query(sql: str, params: tuple = ()):
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            columns = [desc[0] for desc in cur.description]
            rows = cur.fetchall()

    return [dict(zip(columns, row)) for row in rows]


def _filter_markets(researched: list, limit: int) -> list:
    return [
        m for m in researched
        if m.get("research", {}).get("modelable", False)
        and m.get("risk_flag") != "skip"
    ][:limit]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/readyz")
def readyz():
    checks = {"postgres": "unknown", "redis": "unknown"}

    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                cur.fetchone()
        checks["postgres"] = "ok"
    except Exception as e:
        checks["postgres"] = f"error: {e}"

    try:
        r = redis.Redis.from_url(REDIS_URL)
        r.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"

    status = "ok" if all(value == "ok" for value in checks.values()) else "error"
    return {"status": status, "checks": checks}


@app.post("/markets/sync")
async def markets_sync(limit: int = 100):
    return await sync_markets(limit=limit)


@app.get("/stats")
def stats():
    markets_count = db_query("SELECT COUNT(*) AS count FROM markets;")[0]["count"]
    snapshots_count = db_query("SELECT COUNT(*) AS count FROM market_snapshots;")[0]["count"]
    latest_snapshot = db_query(
        "SELECT created_at FROM market_snapshots ORDER BY created_at DESC LIMIT 1;"
    )

    return {
        "markets": markets_count,
        "market_snapshots": snapshots_count,
        "latest_snapshot_at": latest_snapshot[0]["created_at"] if latest_snapshot else None,
    }


@app.get("/markets")
def list_markets(limit: int = 20, offset: int = 0):
    limit = min(limit, 100)
    return db_query(
        """
        SELECT
            m.id, m.polymarket_id, m.question, m.category,
            m.active, m.closed, m.end_date, m.updated_at,
            s.yes_price, s.no_price, s.volume, s.liquidity,
            s.created_at AS snapshot_at
        FROM markets m
        LEFT JOIN LATERAL (
            SELECT *
            FROM market_snapshots s
            WHERE s.market_id = m.id
            ORDER BY s.created_at DESC
            LIMIT 1
        ) s ON TRUE
        ORDER BY m.updated_at DESC
        LIMIT %s OFFSET %s;
        """,
        (limit, offset),
    )


@app.get("/markets/{market_id}")
def get_market(market_id: int):
    rows = db_query(
        """
        SELECT
            m.id, m.polymarket_id, m.question, m.description,
            m.category, m.active, m.closed, m.end_date,
            m.created_at, m.updated_at
        FROM markets m
        WHERE m.id = %s;
        """,
        (market_id,),
    )

    if not rows:
        raise HTTPException(status_code=404, detail="Market not found")

    snapshots = db_query(
        """
        SELECT yes_price, no_price, volume, liquidity, created_at
        FROM market_snapshots
        WHERE market_id = %s
        ORDER BY created_at DESC
        LIMIT 20;
        """,
        (market_id,),
    )

    return {"market": rows[0], "snapshots": snapshots}


@app.get("/markets/{market_id}/agent-history")
def market_agent_history(market_id: int):
    return get_market_agent_history(market_id)


@app.get("/scanner/candidates")
def scanner_candidates(
    limit: int = 20,
    min_liquidity: float = 1000,
    min_volume: float = 10000,
    min_price: float = 0.05,
    max_price: float = 0.95,
):
    return get_candidates(
        limit=limit,
        min_liquidity=min_liquidity,
        min_volume=min_volume,
        min_price=min_price,
        max_price=max_price,
    )


@app.get("/agents/simple-filter")
def simple_filter_agent(limit: int = 20):
    candidates = get_candidates(limit=limit)
    return score_markets(candidates)


@app.get("/agents/research")
def research_agent(limit: int = 20):
    candidates = get_candidates(limit=limit)
    scored = score_markets(candidates)
    return research_markets(scored)


@app.get("/agents/analyze")
async def analyze_agent(limit: int = 1):
    limit = min(limit, 5)
    candidates = get_candidates(limit=limit * 4)
    scored = score_markets(candidates)
    researched = research_markets(scored)
    filtered = _filter_markets(researched, limit)

    results = analyze_markets(filtered)

    for item in results:
        analyst = item.get("analyst") or {}
        try:
            save_agent_run(item["id"], analyst)
        except Exception:
            pass

    return results


@app.get("/agents/consensus")
async def consensus_agent(limit: int = 1):
    limit = min(limit, 5)
    candidates = get_candidates(limit=limit * 4)
    scored = score_markets(candidates)
    researched = research_markets(scored)
    filtered = _filter_markets(researched, limit)

    with_analyst = analyze_markets(filtered)
    with_challenger = challenge_markets(with_analyst)
    results = run_consensus(with_challenger)

    for item in results:
        market_id = item["id"]
        analyst = item.get("analyst") or {}
        challenger = item.get("challenger") or {}
        consensus = item.get("consensus") or {}

        try:
            save_agent_run(market_id, analyst)
        except Exception:
            pass

        try:
            save_agent_run(market_id, challenger)
        except Exception:
            pass

        try:
            save_consensus_decision(market_id, consensus)
        except Exception:
            pass

    return results


@app.get("/agent-runs")
def agent_runs(limit: int = 20):
    return list_agent_runs(limit)


@app.get("/consensus-decisions")
def consensus_decisions(limit: int = 20):
    return list_consensus_decisions(limit)


@app.post("/jobs/run-once")
async def jobs_run_once():
    return await run_experiment_cycle()


@app.post("/jobs/run-once-notify")
async def jobs_run_once_notify():
    return await run_experiment_cycle(notify=True)


@app.get("/jobs/status")
def jobs_status():
    return {
        "scheduler": "not_started",
        "mode": "manual",
        "trigger": "POST /jobs/run-once",
        "cycle_market_limit": 3,
        "sync_limit": 50,
    }


@app.post("/notifications/test")
async def notifications_test():
    result = await send_telegram_message("Polymarket AI Desk notification test OK")
    return result
