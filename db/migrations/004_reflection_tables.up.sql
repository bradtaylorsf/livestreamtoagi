-- Journal entries created during 6-hour and weekly reflection cycles
CREATE TABLE IF NOT EXISTS journal_entries (
    id              SERIAL PRIMARY KEY,
    agent_id        TEXT NOT NULL REFERENCES agents(id),
    reflection_type TEXT NOT NULL CHECK (reflection_type IN ('6hour', 'weekly')),
    content         TEXT NOT NULL,
    token_count     INT  NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_journal_agent ON journal_entries (agent_id);
CREATE INDEX IF NOT EXISTS idx_journal_created ON journal_entries (created_at);

-- Self-modification proposals generated during weekly reflection
CREATE TABLE IF NOT EXISTS self_modification_proposals (
    id              SERIAL PRIMARY KEY,
    agent_id        TEXT NOT NULL REFERENCES agents(id),
    proposal_type   TEXT NOT NULL,
    description     TEXT NOT NULL,
    reasoning       TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_at     TIMESTAMPTZ,
    reviewed_by     TEXT
);

CREATE INDEX IF NOT EXISTS idx_proposals_agent ON self_modification_proposals (agent_id);
CREATE INDEX IF NOT EXISTS idx_proposals_status ON self_modification_proposals (status);
