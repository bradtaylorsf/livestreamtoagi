-- Evolution loop cycle tracking
CREATE TABLE IF NOT EXISTS evolution_cycles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    loop_run_id UUID NOT NULL,
    cycle_number INT NOT NULL,
    simulation_id UUID REFERENCES simulations(id),
    eval_run_id UUID REFERENCES eval_runs(id),
    overall_score DECIMAL(5,2),
    score_delta DECIMAL(5,2),
    changes_applied INT DEFAULT 0,
    issues_filed INT DEFAULT 0,
    config_version_before INT,
    config_version_after INT,
    status VARCHAR(20) NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'completed', 'converged', 'regressed', 'cost_cap', 'failed')),
    cost DECIMAL(10,4) DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_evolution_cycles_loop
    ON evolution_cycles(loop_run_id, cycle_number);
