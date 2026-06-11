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
-- Handedness columns are populated from the player_handedness seed.
-- pitcher_handedness and batter_handedness may still be NULL for player
-- IDs not present in the seed (rare — the seed covers the full cohort of
-- 657 pitchers and 609 batters from the 2024 April + September windows).
-- handedness_matchup is NULL whenever either side is NULL, by design — a
-- partial matchup is not a usable signal.
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
        projected_batter_id,
        lineup_state,
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
),

pitcher_hands AS (
    SELECT
        player_id AS pitcher_id,
        hand AS pitcher_handedness
    FROM {{ ref("player_handedness") }}
    WHERE role = 'pitcher'
),

batter_hands AS (
    SELECT
        player_id AS batter_id,
        hand AS batter_handedness
    FROM {{ ref("player_handedness") }}
    WHERE role = 'batter'
),

projected_batter_hands AS (
    SELECT
        player_id AS projected_batter_id,
        hand AS projected_batter_handedness
    FROM {{ ref("player_handedness") }}
    WHERE role = 'batter'
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
    pe.lineup_state,
    -- Handedness from the player_handedness seed (ADR 0016, milestone day 2).
    ph.pitcher_handedness,
    bh.batter_handedness,
    -- Concatenated matchup for downstream consumers. Reads as 'pitcher_vs_batter'.
    -- NULL on either side propagates to NULL here, by design — a partial
    -- matchup is not a usable matchup signal.
    CASE
        WHEN ph.pitcher_handedness IS NULL OR bh.batter_handedness IS NULL THEN NULL
        ELSE ph.pitcher_handedness || '_vs_' || bh.batter_handedness
    END AS handedness_matchup,
    -- Projected batter + its handedness matchup. Populated only when the
    -- uncertainty window produced a projection (projected_batter_id not null).
    -- This is what the system WOULD have computed during the window, before
    -- the real lineup confirmed. The reduced-confidence signal is keyed on
    -- this, not on the real matchup (ADR 0020).
    pe.projected_batter_id,
    pbh.projected_batter_handedness,
    CASE
        WHEN ph.pitcher_handedness IS NULL OR pbh.projected_batter_handedness IS NULL THEN NULL
        ELSE ph.pitcher_handedness || '_vs_' || pbh.projected_batter_handedness
    END AS projected_handedness_matchup,
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
LEFT JOIN pitcher_hands AS ph
    ON pe.pitcher_id = ph.pitcher_id
LEFT JOIN batter_hands AS bh
    ON pe.batter_id = bh.batter_id
LEFT JOIN projected_batter_hands AS pbh
    ON pe.projected_batter_id = pbh.projected_batter_id
WHERE NOT pe.is_duplicate
