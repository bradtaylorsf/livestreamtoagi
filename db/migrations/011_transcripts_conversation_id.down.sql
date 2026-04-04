DROP INDEX IF EXISTS idx_transcripts_conversation_id;
ALTER TABLE transcripts DROP COLUMN IF EXISTS conversation_id;
