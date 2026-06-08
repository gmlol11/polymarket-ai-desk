CREATE TABLE IF NOT EXISTS agent_runs (
    id SERIAL PRIMARY KEY,
    market_id INTEGER REFERENCES markets(id) ON DELETE CASCADE,
    agent_name TEXT NOT NULL,
    schema_version TEXT,
    estimated_probability NUMERIC(6, 4),
    confidence NUMERIC(6, 4),
    recommended_side TEXT,
    output_json JSONB,
    error TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_market_id ON agent_runs(market_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_agent_name ON agent_runs(agent_name);
CREATE INDEX IF NOT EXISTS idx_agent_runs_created_at ON agent_runs(created_at DESC);

CREATE TABLE IF NOT EXISTS consensus_decisions (
    id SERIAL PRIMARY KEY,
    market_id INTEGER REFERENCES markets(id) ON DELETE CASCADE,
    market_probability NUMERIC(6, 4),
    claude_probability NUMERIC(6, 4),
    challenger_probability NUMERIC(6, 4),
    consensus_probability NUMERIC(6, 4),
    edge NUMERIC(6, 4),
    confidence NUMERIC(6, 4),
    recommended_side TEXT,
    decision TEXT,
    reason TEXT,
    output_json JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_consensus_decisions_market_id ON consensus_decisions(market_id);
CREATE INDEX IF NOT EXISTS idx_consensus_decisions_decision ON consensus_decisions(decision);
CREATE INDEX IF NOT EXISTS idx_consensus_decisions_created_at ON consensus_decisions(created_at DESC);
