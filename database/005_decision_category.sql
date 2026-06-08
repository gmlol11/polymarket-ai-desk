-- Persist the runtime category_guess on each consensus decision so weekly
-- analytics and the diversity audit can break decisions down by category.
-- (markets.category from Polymarket is usually empty; category_guess is computed
--  by agents/simple_filter at analysis time and was previously not stored.)
--
-- Run once: docker exec -i polymarket_postgres psql -U polymarket_user -d polymarket_ai_desk < database/005_decision_category.sql

ALTER TABLE consensus_decisions
    ADD COLUMN IF NOT EXISTS category_guess TEXT;

CREATE INDEX IF NOT EXISTS idx_consensus_decisions_category
    ON consensus_decisions(category_guess);
