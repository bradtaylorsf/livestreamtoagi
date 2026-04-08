-- Remove CHECK constraints added in 029
ALTER TABLE agent_internal_state
    DROP CONSTRAINT IF EXISTS chk_energy_range,
    DROP CONSTRAINT IF EXISTS chk_satisfaction_range,
    DROP CONSTRAINT IF EXISTS chk_boredom_range,
    DROP CONSTRAINT IF EXISTS chk_frustration_range,
    DROP CONSTRAINT IF EXISTS chk_social_need_range,
    DROP CONSTRAINT IF EXISTS chk_creative_need_range,
    DROP CONSTRAINT IF EXISTS chk_recognition_need_range;

ALTER TABLE alliance_proposals
    DROP CONSTRAINT IF EXISTS chk_proposal_status;

ALTER TABLE alliances
    DROP CONSTRAINT IF EXISTS chk_treasury_non_negative;
