{{
    config(
        materialized="incremental",
        unique_key=["game_pk", "at_bat_number", "pitch_number"],
    )
}}

-- silver_matchup_events
--
-- Thin matchup view derived from silver_pitch_events. Per ADR 0016, this
-- milestone keeps the model lean: only the natural key plus the columns
-- that define the matchup itself (pitcher, batter, lineup_state, and the
-- pitch-level identifiers needed to join back to silver_pitch_events for
-- everything else).
--
-- Handedness columns are populated as NULL in this initial slice. The
-- player_handedness seed and join lands on 2026-06-02 (milestone day 2),
-- at which point handedness will be wired in via macro or seed-driven
-- join. Until then, downstream consumers must treat handedness columns
-- as nullable and not panic.
--
-- fatigue_bucket_join carries the pitcher's fatigue bucket from
-- silver_pitcher_game_fatigue at the (game_pk, pitcher_id) grain. This
-- is the only denormalized column intentionally included — fatigue is a
-- load-bearing dimension of every matchup signal per the Phase 2 plan
-- and joining it lazily at signal-generation time would force the same
-- join in every downstream consumer.

WITH pitch_events AS (
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
        is_late_arrival,
        is_duplicate,
        correction_of,
        ingestion_time
    FROM {{ ref("silver_pitch_events") }}

    {% if is_incremental() %}
    WHERE event_time >= (
        SELECT COALESCE(MAX(event_time), TIMESTAMP '1900-01-01 00:00:00')
        FROM {{ this }}
    )
    {% endif %}
),

fatigue AS (
    SELECT
        game_pk,
        pitcher_id,
        fatigue_bucket
    FROM {{ ref("silver_pitcher_game_fatigue") }}
)

SELECT
    pe.event_time,
    pe.event_day,
    pe.game_pk,
    pe.at_bat_number,
    pe.pitch_number,
    pe.inning,
    pe.inning_topbot,
    pe.pitcher_id,
    pe.batter_id,
    -- Handedness columns populated on milestone day 2 via player_handedness seed.
    CAST(NULL AS VARCHAR) AS pitcher_handedness,
    CAST(NULL AS VARCHAR) AS batter_handedness,
    CAST(NULL AS VARCHAR) AS handedness_matchup,
    -- Fatigue context joined from the pitcher-game-level signal.
    f.fatigue_bucket AS pitcher_fatigue_bucket,
    -- Audit columns inherited so downstream tests can use them directly.
    pe.is_late_arrival,
    pe.is_duplicate,
    pe.correction_of,
    pe.ingestion_time,
    CURRENT_TIMESTAMP AS computed_at
FROM pitch_events AS pe
LEFT JOIN fatigue AS f
    ON pe.game_pk = f.game_pk
    AND pe.pitcher_id = f.pitcher_id
WHERE NOT pe.is_duplicate
