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

# ── Paper trading ─────────────────────────────────────────────────────────
# Fixed stake per paper trade (USD). No real funds are used.
PAPER_TRADE_STAKE_USD: float = _float("PAPER_TRADE_STAKE_USD", 1.0)

# ── BET decision thresholds ───────────────────────────────────────────────
# Minimum edge required to trigger a BET decision
BET_MIN_EDGE: float = _float("BET_MIN_EDGE", 0.05)

# Minimum average agent confidence required to trigger a BET decision
BET_MIN_CONFIDENCE: float = _float("BET_MIN_CONFIDENCE", 0.65)
