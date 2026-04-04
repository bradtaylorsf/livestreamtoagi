-- Add conversation_id FK to transcripts so we can look up a conversation's transcript
ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS conversation_id UUID REFERENCES conversations(id);
CREATE INDEX IF NOT EXISTS idx_transcripts_conversation_id ON transcripts (conversation_id) WHERE conversation_id IS NOT NULL;
