-- Add image_url column to journal_entries for AI-generated illustrations
ALTER TABLE journal_entries ADD COLUMN IF NOT EXISTS image_url TEXT DEFAULT NULL;
