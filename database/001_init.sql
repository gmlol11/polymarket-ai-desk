CREATE TABLE IF NOT EXISTS markets (
    id SERIAL PRIMARY KEY,
    polymarket_id TEXT UNIQUE,
    question TEXT NOT NULL,
    description TEXT,
    category TEXT,
    active BOOLEAN DEFAULT TRUE,
    closed BOOLEAN DEFAULT FALSE,
    end_date TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS market_snapshots (
    id SERIAL PRIMARY KEY,
    market_id INTEGER REFERENCES markets(id) ON DELETE CASCADE,
    yes_price NUMERIC(10, 4),
    no_price NUMERIC(10, 4),
    volume NUMERIC(18, 4),
    liquidity NUMERIC(18, 4),
    raw JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS recommendations (
    id SERIAL PRIMARY KEY,
    market_id INTEGER REFERENCES markets(id) ON DELETE CASCADE,
    recommended_side TEXT CHECK (recommended_side IN ('YES', 'NO')),
    market_probability NUMERIC(6, 4),
    model_probability NUMERIC(6, 4),
    edge NUMERIC(6, 4),
    confidence TEXT,
    recommended_amount NUMERIC(10, 2),
    reasoning TEXT,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT NOW()
);
