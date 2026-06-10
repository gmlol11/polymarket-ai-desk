import os

import psycopg
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://polymarket_user:polymarket_password@localhost:5433/polymarket_ai_desk",
)


def get_candidates(
    limit: int = 20,
    min_liquidity: float = 1000,
    min_volume: float = 10000,
    min_price: float = 0.05,
    max_price: float = 0.95,
):
    limit = min(limit, 2000)

    sql = """
        SELECT
            m.id,
            m.polymarket_id,
            m.question,
            m.category,
            m.active,
            m.closed,
            m.end_date,
            s.yes_price,
            s.no_price,
            s.volume,
            s.liquidity,
            s.created_at AS snapshot_at
        FROM markets m
        JOIN LATERAL (
            SELECT *
            FROM market_snapshots s
            WHERE s.market_id = m.id
            ORDER BY s.created_at DESC
            LIMIT 1
        ) s ON TRUE
        WHERE
            m.active = TRUE
            AND m.closed = FALSE
            AND s.liquidity >= %s
            AND s.volume >= %s
            AND s.yes_price >= %s
            AND s.yes_price <= %s
        ORDER BY s.liquidity DESC
        LIMIT %s;
    """

    with psycopg.connect(DATABASE_URL, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    min_liquidity,
                    min_volume,
                    min_price,
                    max_price,
                    limit,
                ),
            )

            columns = [desc[0] for desc in cur.description]
            rows = cur.fetchall()

    return [dict(zip(columns, row)) for row in rows]
