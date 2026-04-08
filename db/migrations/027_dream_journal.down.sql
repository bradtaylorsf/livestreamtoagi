ALTER TABLE journal_entries DROP COLUMN IF EXISTS entry_type;

-- Restore previous reflection_type constraint (without 'dream')
ALTER TABLE journal_entries DROP CONSTRAINT IF EXISTS journal_entries_reflection_type_check;
ALTER TABLE journal_entries ADD CONSTRAINT journal_entries_reflection_type_check
    CHECK (reflection_type IN ('6hour', 'weekly', 'conversation'));
