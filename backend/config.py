"""
Experiment configuration.

All values are read from environment variables with safe defaults —
no env var is required. Do not import secrets or API keys here.

Override by setting variables in .env (see .env.example).
"""

import os


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name) or default)
    except (ValueError, TypeError):
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name) or default)
    except (ValueError, TypeError):
        return default


# ── Experiment runner ──────────────────────────────────────────────────────
# How many markets to sync from Polymarket per cycle
EXPERIMENT_SYNC_LIMIT: int = _int("EXPERIMENT_SYNC_LIMIT", 500)

# Max markets to analyze (run through both AI agents) per cycle
EXPERIMENT_MARKET_LIMIT: int = _int("EXPERIMENT_MARKET_LIMIT", 25)

# Skip re-analyzing a market if it was analyzed within this many hours
EXPERIMENT_REANALYZE_COOLDOWN_HOURS: int = _int("EXPERIMENT_REANALYZE_COOLDOWN_HOURS", 48)

# Skip markets that resolve within this many days — live / imminent events
# (e.g. an in-progress sports final) where the AI agents have no real-time data
# and the market price is far better informed than the model.
# Set to 0 to disable.
EXPERIMENT_MIN_DAYS_TO_RESOLUTION: int = _int("EXPERIMENT_MIN_DAYS_TO_RESOLUTION", 3)

# ── Paper trading ─────────────────────────────────────────────────────────
# Fixed stake per paper trade (USD). No real funds are used.
PAPER_TRADE_STAKE_USD: float = _float("PAPER_TRADE_STAKE_USD", 1.0)

# ── BET decision thresholds ───────────────────────────────────────────────
# Minimum edge required to trigger a BET decision
BET_MIN_EDGE: float = _float("BET_MIN_EDGE", 0.05)

# Minimum average agent confidence required to trigger a BET decision
BET_MIN_CONFIDENCE: float = _float("BET_MIN_CONFIDENCE", 0.65)

# Maximum *plausible* edge for an auto-BET. On liquid markets a real edge above
# this almost never exists — such gaps are model blind spots (live events the
# model can't see, proxy/joke markets, stale prices). Edges above this are
# downgraded to NEEDS_MORE_RESEARCH for human review instead of auto-betting.
BET_MAX_EDGE: float = _float("BET_MAX_EDGE", 0.25)
