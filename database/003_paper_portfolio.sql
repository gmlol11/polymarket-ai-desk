CREATE TABLE IF NOT EXISTS paper_trades (
    id SERIAL PRIMARY KEY,
    consensus_decision_id INTEGER REFERENCES consensus_decisions(id) ON DELETE CASCADE,
    market_id INTEGER REFERENCES markets(id) ON DELETE CASCADE,
    side TEXT NOT NULL,
    entry_probability NUMERIC(6, 4),
    stake_usd NUMERIC(10, 2),
    simulated_shares NUMERIC(18, 6),
    status TEXT DEFAULT 'open',
    exit_probability NUMERIC(6, 4),
    realized_pnl NUMERIC(10, 4),
    opened_at TIMESTAMP DEFAULT NOW(),
    closed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_paper_trades_market_id ON paper_trades(market_id);
CREATE INDEX IF NOT EXISTS idx_paper_trades_status ON paper_trades(status);
CREATE INDEX IF NOT EXISTS idx_paper_trades_opened_at ON paper_trades(opened_at DESC);

CREATE TABLE IF NOT EXISTS experiment_metrics (
    id SERIAL PRIMARY KEY,
    metric_name TEXT NOT NULL,
    metric_value JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_experiment_metrics_name ON experiment_metrics(metric_name);
