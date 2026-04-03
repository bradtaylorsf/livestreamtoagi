-- Revert self-modification fields
ALTER TABLE self_modification_proposals
    DROP COLUMN IF EXISTS file,
    DROP COLUMN IF EXISTS new_content,
    DROP COLUMN IF EXISTS impact_notes;

ALTER TABLE self_modification_proposals
    DROP CONSTRAINT IF EXISTS self_modification_proposals_status_check;

ALTER TABLE self_modification_proposals
    ADD CONSTRAINT self_modification_proposals_status_check
    CHECK (status IN ('pending', 'approved', 'rejected'));
