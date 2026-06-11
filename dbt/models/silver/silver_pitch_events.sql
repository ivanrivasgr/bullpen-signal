{{
    config(
        materialized="incremental",
        unique_key=["game_pk", "at_bat_number", "pitch_number"],
    )
}}

WITH bronze AS (
    SELECT
        event_time,
        CAST(event_time AS DATE) AS event_day,
        game_pk,
        at_bat_number,
        pitch_number,
        inning,
        inning_topbot,
        pitcher_id,
        batter_id,
        projected_batter_id,
        pitch_type,
        release_speed,
        release_spin_rate,
        plate_x,
        plate_z,
        zone,
        balls,
        strikes,
        outs_when_up,
        on_1b,
        on_2b,
        on_3b,
        home_score,
        away_score,
        description,
        events,
        is_late_arrival,
        is_duplicate,
        correction_of,
        lineup_state,
        ingestion_time,
        kafka_partition,
        source_offset
    FROM {{ source("bronze", "pitches") }}

    {% if is_incremental() %}
    WHERE event_time >= (
        SELECT COALESCE(MAX(event_time), TIMESTAMP '1900-01-01 00:00:00')
        FROM {{ this }}
    )
    {% endif %}
)

SELECT
    event_time,
    event_day,
    game_pk,
    at_bat_number,
    pitch_number,
    inning,
    inning_topbot,
    pitcher_id,
    batter_id,
    projected_batter_id,
    pitch_type,
    release_speed,
    release_spin_rate,
    plate_x,
    plate_z,
    zone,
    balls,
    strikes,
    outs_when_up,
    on_1b,
    on_2b,
    on_3b,
    home_score,
    away_score,
    description,
    events,
    is_late_arrival,
    is_duplicate,
    correction_of,
    lineup_state,
    ingestion_time,
    kafka_partition,
    source_offset
FROM bronze
