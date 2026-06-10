import os

import psycopg
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://polymarket_user:polymarket_password@localhost:5433/polymarket_ai_desk",
)


def get_connection():
    # connect_timeout: a stalled DB (e.g. Docker VM resuming after system sleep)
    # must fail fast instead of blocking the single-threaded event loop forever.
    return psycopg.connect(DATABASE_URL, connect_timeout=10)
