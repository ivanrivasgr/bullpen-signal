-- Natural key uniqueness for mart_should_have_fired_ledger.
-- One row per pitch (game_pk, at_bat_number, pitch_number) where
-- confidence_band IN ('reduced', 'suppressed').
SELECT
    game_pk,
    at_bat_number,
    pitch_number,
    COUNT(*) AS occurrences
FROM {{ ref("mart_should_have_fired_ledger") }}
GROUP BY game_pk, at_bat_number, pitch_number
HAVING COUNT(*) > 1
