-- Dream journal — distinguish dream entries from reflection journals
ALTER TABLE journal_entries ADD COLUMN IF NOT EXISTS entry_type VARCHAR(20) DEFAULT 'reflection';
