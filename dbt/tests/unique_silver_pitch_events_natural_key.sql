SELECT
    game_pk,
    at_bat_number,
    pitch_number,
    COUNT(*) AS row_count
FROM {{ ref("silver_pitch_events") }}
GROUP BY
    game_pk,
    at_bat_number,
    pitch_number
HAVING COUNT(*) > 1
