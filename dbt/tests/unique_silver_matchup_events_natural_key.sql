-- Natural key uniqueness test for silver_matchup_events.
-- Matches the pattern of unique_silver_pitch_events_natural_key.sql.
SELECT
    game_pk,
    at_bat_number,
    pitch_number,
    COUNT(*) AS occurrences
FROM {{ ref("silver_matchup_events") }}
GROUP BY game_pk, at_bat_number, pitch_number
HAVING COUNT(*) > 1
