{{ config(materialized="table") }}

SELECT
    game_pk,
    pitcher_id,
    MIN(event_time)         AS first_pitch_time,
    MAX(event_time)         AS last_pitch_time,
    COUNT(*)                AS pitch_count,
    MAX(inning)             AS max_inning,
    AVG(release_speed)      AS avg_release_speed,
    AVG(release_spin_rate)  AS avg_release_spin_rate,
    CASE
        WHEN COUNT(*) < 25 THEN 'low'
        WHEN COUNT(*) < 50 THEN 'medium'
        ELSE 'high'
    END                     AS fatigue_bucket,
    CURRENT_TIMESTAMP       AS computed_at
FROM {{ ref("silver_pitch_events") }}
WHERE NOT is_duplicate
GROUP BY game_pk, pitcher_id
