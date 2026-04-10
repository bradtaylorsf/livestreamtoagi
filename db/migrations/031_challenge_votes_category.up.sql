-- 031: Add votes and category columns to challenges table
ALTER TABLE challenges ADD COLUMN IF NOT EXISTS votes INTEGER DEFAULT 0;
ALTER TABLE challenges ADD COLUMN IF NOT EXISTS category VARCHAR(50);
