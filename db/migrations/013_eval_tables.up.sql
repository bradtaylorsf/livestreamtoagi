-- Migration 013: Add eval_runs and eval_results tables for the evaluation framework.

CREATE TABLE eval_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    simulation_id UUID REFERENCES simulations(id) NOT NULL,
    eval_suite TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    overall_score DECIMAL(5,2),
    cost DECIMAL(10,4) DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE eval_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    eval_run_id UUID REFERENCES eval_runs(id) NOT NULL,
    category TEXT NOT NULL,
    score DECIMAL(5,2),
    reasoning TEXT,
    evidence JSONB,
    sub_scores JSONB,
    tokens_used INT DEFAULT 0,
    cost DECIMAL(10,4) DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_eval_runs_simulation ON eval_runs(simulation_id);
CREATE INDEX idx_eval_results_run ON eval_results(eval_run_id);
CREATE INDEX idx_eval_results_category ON eval_results(category);
