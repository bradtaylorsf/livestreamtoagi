-- Revert: remove 'conversation' from allowed reflection_type values
-- NOTE: This will fail if rows with reflection_type='conversation' exist.
ALTER TABLE journal_entries DROP CONSTRAINT IF EXISTS journal_entries_reflection_type_check;
ALTER TABLE journal_entries ADD CONSTRAINT journal_entries_reflection_type_check
    CHECK (reflection_type IN ('6hour', 'weekly'));
