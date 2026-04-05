-- Eval analysis results storage
CREATE TABLE IF NOT EXISTS eval_analyses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    eval_run_id UUID NOT NULL REFERENCES eval_runs(id),
    summary TEXT,
    confidence DECIMAL(3,2),
    proposals JSONB NOT NULL DEFAULT '[]',
    trend_data JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_eval_analyses_run
    ON eval_analyses(eval_run_id);
