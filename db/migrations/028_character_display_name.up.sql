-- Add display_name column to character_applications (#275)
ALTER TABLE character_applications ADD COLUMN IF NOT EXISTS display_name VARCHAR(100);
