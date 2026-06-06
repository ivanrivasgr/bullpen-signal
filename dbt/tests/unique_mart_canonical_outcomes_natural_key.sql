-- Natural key uniqueness for mart_canonical_outcomes.
-- One row per (game_pk, at_bat_number).
SELECT
    game_pk,
    at_bat_number,
    COUNT(*) AS occurrences
FROM {{ ref("mart_canonical_outcomes") }}
GROUP BY game_pk, at_bat_number
HAVING COUNT(*) > 1
