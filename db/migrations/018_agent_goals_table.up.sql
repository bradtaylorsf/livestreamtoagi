-- Persistent agent goals table (replaces Redis-backed goals)
CREATE TABLE IF NOT EXISTS agent_goals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id VARCHAR(50) NOT NULL REFERENCES agents(id),
    goal TEXT NOT NULL,
    priority INT NOT NULL DEFAULT 5,
    status VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'completed', 'abandoned', 'blocked')),
    source VARCHAR(20) DEFAULT 'self'
        CHECK (source IN ('self', 'assigned', 'eval_loop', 'reflection')),
    progress_notes TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ,
    parent_goal_id UUID REFERENCES agent_goals(id)
);

CREATE INDEX IF NOT EXISTS idx_agent_goals_agent_status
    ON agent_goals(agent_id, status);
CREATE INDEX IF NOT EXISTS idx_agent_goals_parent
    ON agent_goals(parent_goal_id) WHERE parent_goal_id IS NOT NULL;
