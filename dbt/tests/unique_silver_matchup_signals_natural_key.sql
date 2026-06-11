-- Natural key uniqueness test for silver_matchup_signals.
-- The natural key includes lineup_state_at_emission because an uncertain
-- pitch legitimately emits two rows (ADR 0020): a reduced signal from the
-- projected handedness and a full signal from the real handedness. The
-- pitch identity plus the emission state is what must be unique.
-- Matches the pattern used by silver_pitch_events, silver_pitcher_game_fatigue,
-- and silver_matchup_events.
SELECT
    game_pk,
    at_bat_number,
    pitch_number,
    lineup_state_at_emission,
    COUNT(*) AS occurrences
FROM {{ ref("silver_matchup_signals") }}
GROUP BY game_pk, at_bat_number, pitch_number, lineup_state_at_emission
HAVING COUNT(*) > 1
