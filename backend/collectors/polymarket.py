import json
from datetime import datetime
from typing import Any

import httpx
from psycopg.types.json import Jsonb

from backend.db.connection import get_connection


GAMMA_MARKETS_URL = "https://gamma-api.polymarket.com/markets"


async def fetch_market_status(polymarket_id: str) -> dict[str, Any] | None:
    """
    Fetch a single market by its Polymarket id, regardless of closed status.

    The daily sync only pulls active/open markets, so a resolved market drops
    out of it entirely. Resolution tracking re-fetches by id to read the final
    outcome. Returns the market dict, or None on any error / not found.
    """
    url = f"{GAMMA_MARKETS_URL}/{polymarket_id}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url)
            if response.status_code != 200:
                return None
            data = response.json()
    except Exception:
        return None

    if isinstance(data, list):
        return data[0] if data else None
    return data


def parse_resolution(market: dict[str, Any] | None) -> str | None:
    """
    Determine a cleanly-resolved binary outcome.

    Returns "YES" or "NO" if the market is closed and one outcome resolved to ~1
    while the other resolved to ~0. Returns None if the market is still open, was
    voided (e.g. outcomePrices ["0","0"]), or is otherwise not cleanly resolved.

    Gamma shape: outcomes='["Yes", "No"]', outcomePrices='["1", "0"]' (YES won)
    or '["0", "1"]' (NO won), both JSON-encoded strings.
    """
    if not market or not market.get("closed"):
        return None

    outcomes = market.get("outcomes")
    prices = market.get("outcomePrices")
    if isinstance(outcomes, str):
        try:
            outcomes = json.loads(outcomes)
        except Exception:
            return None
    if isinstance(prices, str):
        try:
            prices = json.loads(prices)
        except Exception:
            return None
    if not outcomes or not prices or len(outcomes) != len(prices):
        return None

    resolved: dict[str, float] = {}
    for label, price in zip(outcomes, prices):
        try:
            resolved[str(label).strip().lower()] = float(price)
        except (TypeError, ValueError):
            return None

    yes = resolved.get("yes")
    no = resolved.get("no")
    if yes is None or no is None:
        return None

    WIN_THRESHOLD = 0.99
    if yes >= WIN_THRESHOLD and no <= (1 - WIN_THRESHOLD):
        return "YES"
    if no >= WIN_THRESHOLD and yes <= (1 - WIN_THRESHOLD):
        return "NO"
    return None  # void / disputed / not cleanly resolved


def _parse_datetime(value: str | None):
    if not value:
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _to_float(value: Any):
    if value is None:
        return None

    try:
        return float(value)
    except Exception:
        return None


# Gamma API caps a single page at 100 markets — paginate with offset to get more.
GAMMA_PAGE_SIZE = 100


async def fetch_markets(limit: int = 100) -> list[dict[str, Any]]:
    """
    Fetch up to `limit` active, open markets from the Polymarket Gamma API.

    The API returns at most GAMMA_PAGE_SIZE (100) markets per request, so for
    larger limits we paginate using the `offset` parameter until we have enough
    or the API runs out of markets.
    """
    collected: list[dict[str, Any]] = []
    offset = 0

    async with httpx.AsyncClient(timeout=30) as client:
        while len(collected) < limit:
            page_size = min(GAMMA_PAGE_SIZE, limit - len(collected))
            params = {
                "active": "true",
                "closed": "false",
                "limit": page_size,
                "offset": offset,
            }

            response = await client.get(GAMMA_MARKETS_URL, params=params)
            response.raise_for_status()
            data = response.json()

            page = data if isinstance(data, list) else data.get("markets", [])
            if not page:
                break  # no more markets available

            collected.extend(page)
            offset += len(page)

            if len(page) < page_size:
                break  # last page reached

    return collected[:limit]


async def sync_markets(limit: int = 100) -> dict[str, Any]:
    markets = await fetch_markets(limit=limit)

    inserted_or_updated = 0
    snapshots_inserted = 0

    with get_connection() as conn:
        with conn.cursor() as cur:
            for item in markets:
                polymarket_id = str(
                    item.get("id")
                    or item.get("conditionId")
                    or item.get("slug")
                )

                question = (
                    item.get("question")
                    or item.get("title")
                    or item.get("slug")
                    or "Untitled market"
                )

                description = item.get("description")
                category = item.get("category")
                active = bool(item.get("active", True))
                closed = bool(item.get("closed", False))
                end_date = _parse_datetime(item.get("endDate") or item.get("endDateIso"))

                cur.execute(
                    """
                    INSERT INTO markets (
                        polymarket_id,
                        question,
                        description,
                        category,
                        active,
                        closed,
                        end_date,
                        updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (polymarket_id)
                    DO UPDATE SET
                        question = EXCLUDED.question,
                        description = EXCLUDED.description,
                        category = EXCLUDED.category,
                        active = EXCLUDED.active,
                        closed = EXCLUDED.closed,
                        end_date = EXCLUDED.end_date,
                        updated_at = NOW()
                    RETURNING id;
                    """,
                    (
                        polymarket_id,
                        question,
                        description,
                        category,
                        active,
                        closed,
                        end_date,
                    ),
                )

                market_id = cur.fetchone()[0]
                inserted_or_updated += 1

                yes_price = _to_float(item.get("bestAsk") or item.get("lastTradePrice"))
                no_price = None

                if yes_price is not None:
                    no_price = round(1 - yes_price, 4)

                volume = _to_float(item.get("volume") or item.get("volumeNum"))
                liquidity = _to_float(item.get("liquidity") or item.get("liquidityNum"))

                cur.execute(
                    """
                    INSERT INTO market_snapshots (
                        market_id,
                        yes_price,
                        no_price,
                        volume,
                        liquidity,
                        raw
                    )
                    VALUES (%s, %s, %s, %s, %s, %s);
                    """,
                    (
                        market_id,
                        yes_price,
                        no_price,
                        volume,
                        liquidity,
                        Jsonb(item),
                    ),
                )

                snapshots_inserted += 1

        conn.commit()

    return {
        "fetched": len(markets),
        "markets_inserted_or_updated": inserted_or_updated,
        "snapshots_inserted": snapshots_inserted,
    }
