-- Allow 'conversation' as a journal reflection_type (in addition to '6hour' and 'weekly')
ALTER TABLE journal_entries DROP CONSTRAINT IF EXISTS journal_entries_reflection_type_check;
ALTER TABLE journal_entries ADD CONSTRAINT journal_entries_reflection_type_check
    CHECK (reflection_type IN ('6hour', 'weekly', 'conversation'));
