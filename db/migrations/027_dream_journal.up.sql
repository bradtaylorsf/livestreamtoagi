-- Dream journal — distinguish dream entries from reflection journals
ALTER TABLE journal_entries ADD COLUMN IF NOT EXISTS entry_type VARCHAR(20) DEFAULT 'reflection';

-- Allow 'dream' as a valid reflection_type for dream journal entries
ALTER TABLE journal_entries DROP CONSTRAINT IF EXISTS journal_entries_reflection_type_check;
ALTER TABLE journal_entries ADD CONSTRAINT journal_entries_reflection_type_check
    CHECK (reflection_type IN ('6hour', 'weekly', 'conversation', 'dream'));
