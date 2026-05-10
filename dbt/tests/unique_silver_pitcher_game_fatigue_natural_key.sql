SELECT
    game_pk,
    pitcher_id,
    COUNT(*) AS row_count
FROM {{ ref("silver_pitcher_game_fatigue") }}
GROUP BY
    game_pk,
    pitcher_id
HAVING COUNT(*) > 1
