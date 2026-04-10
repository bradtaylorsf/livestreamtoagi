-- Remove image_url column from journal_entries
ALTER TABLE journal_entries DROP COLUMN IF EXISTS image_url;
