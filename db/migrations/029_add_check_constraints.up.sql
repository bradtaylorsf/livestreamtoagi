-- Add CHECK constraints for float columns that must be in [0.0, 1.0]
-- and status enums that must match expected values.
-- Uses DO blocks to be idempotent (safe to re-run).

DO $$ BEGIN
    -- agent_internal_state: all float columns are clamped [0, 1]
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_energy_range') THEN
        ALTER TABLE agent_internal_state ADD CONSTRAINT chk_energy_range CHECK (energy >= 0.0 AND energy <= 1.0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_satisfaction_range') THEN
        ALTER TABLE agent_internal_state ADD CONSTRAINT chk_satisfaction_range CHECK (satisfaction >= 0.0 AND satisfaction <= 1.0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_boredom_range') THEN
        ALTER TABLE agent_internal_state ADD CONSTRAINT chk_boredom_range CHECK (boredom >= 0.0 AND boredom <= 1.0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_frustration_range') THEN
        ALTER TABLE agent_internal_state ADD CONSTRAINT chk_frustration_range CHECK (frustration >= 0.0 AND frustration <= 1.0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_social_need_range') THEN
        ALTER TABLE agent_internal_state ADD CONSTRAINT chk_social_need_range CHECK (social_need >= 0.0 AND social_need <= 1.0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_creative_need_range') THEN
        ALTER TABLE agent_internal_state ADD CONSTRAINT chk_creative_need_range CHECK (creative_need >= 0.0 AND creative_need <= 1.0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_recognition_need_range') THEN
        ALTER TABLE agent_internal_state ADD CONSTRAINT chk_recognition_need_range CHECK (recognition_need >= 0.0 AND recognition_need <= 1.0);
    END IF;

    -- alliance_proposals: status must be a known value
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_proposal_status') THEN
        ALTER TABLE alliance_proposals ADD CONSTRAINT chk_proposal_status CHECK (status IN ('pending', 'accepted', 'rejected', 'expired'));
    END IF;

    -- alliances: treasury cannot go negative
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_treasury_non_negative') THEN
        ALTER TABLE alliances ADD CONSTRAINT chk_treasury_non_negative CHECK (shared_treasury >= 0);
    END IF;
END $$;
