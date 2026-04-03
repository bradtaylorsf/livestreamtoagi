-- Add file, new_content, impact_notes columns and expand status enum for self-modification tools
ALTER TABLE self_modification_proposals
    ADD COLUMN IF NOT EXISTS file TEXT,
    ADD COLUMN IF NOT EXISTS new_content TEXT,
    ADD COLUMN IF NOT EXISTS impact_notes TEXT;

-- Update status CHECK constraint to support new statuses
ALTER TABLE self_modification_proposals
    DROP CONSTRAINT IF EXISTS self_modification_proposals_status_check;

ALTER TABLE self_modification_proposals
    ADD CONSTRAINT self_modification_proposals_status_check
    CHECK (status IN ('pending', 'queued_for_review', 'approved', 'rejected', 'auto_approved'));

-- Update existing 'pending' rows to 'queued_for_review'
UPDATE self_modification_proposals SET status = 'queued_for_review' WHERE status = 'pending';
