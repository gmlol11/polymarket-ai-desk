-- Add mark-to-market columns to paper_trades.
-- Run once: docker exec -i polymarket_postgres psql -U polymarket_user -d polymarket_ai_desk < database/004_paper_mark_to_market.sql

ALTER TABLE paper_trades
    ADD COLUMN IF NOT EXISTS current_probability NUMERIC(6, 4),
    ADD COLUMN IF NOT EXISTS unrealized_pnl      NUMERIC(10, 4),
    ADD COLUMN IF NOT EXISTS last_marked_at      TIMESTAMP;

CREATE INDEX IF NOT EXISTS idx_paper_trades_last_marked
    ON paper_trades(last_marked_at DESC NULLS LAST);
