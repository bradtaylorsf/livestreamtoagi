-- Add category column to agent_goals for goal classification
ALTER TABLE agent_goals ADD COLUMN IF NOT EXISTS category VARCHAR(20)
    CHECK (category IN ('creative', 'social', 'economic', 'personal', 'competitive'));
