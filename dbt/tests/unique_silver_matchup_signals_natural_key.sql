-- Natural key uniqueness test for silver_matchup_signals.
-- Matches the pattern used by silver_pitch_events, silver_pitcher_game_fatigue,
-- and silver_matchup_events.
SELECT
    game_pk,
    at_bat_number,
    pitch_number,
    COUNT(*) AS occurrences
FROM {{ ref("silver_matchup_signals") }}
GROUP BY game_pk, at_bat_number, pitch_number
HAVING COUNT(*) > 1
