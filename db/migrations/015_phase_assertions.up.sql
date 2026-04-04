-- Migration 015: Add phase_assertions table for per-phase validation results.

CREATE TABLE IF NOT EXISTS phase_assertions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    simulation_id UUID REFERENCES simulations(id),
    phase_name TEXT NOT NULL,
    assertion_name TEXT NOT NULL,
    passed BOOLEAN NOT NULL,
    expected JSONB,
    actual JSONB,
    severity TEXT NOT NULL DEFAULT 'warning',
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_phase_assertions_simulation
    ON phase_assertions(simulation_id);
CREATE INDEX IF NOT EXISTS idx_phase_assertions_phase
    ON phase_assertions(simulation_id, phase_name);
