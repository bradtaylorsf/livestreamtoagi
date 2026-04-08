-- Revert: remove 'dream' from allowed source values
ALTER TABLE agent_goals DROP CONSTRAINT IF EXISTS agent_goals_source_check;
ALTER TABLE agent_goals ADD CONSTRAINT agent_goals_source_check
    CHECK (source IN ('self', 'assigned', 'eval_loop', 'reflection'));
