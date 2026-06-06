{{
    config(
        materialized="table",
    )
}}

-- mart_canonical_outcomes
--
-- One row per (game_pk, at_bat_number) with the realized outcome of that
-- at-bat. Derived from silver_pitch_events by collapsing the per-pitch
-- rows into one row per at-bat, keeping the final pitch's `events` field
-- (which Statcast populates only on the at-bat-ending pitch) as the
-- canonical outcome.
--
-- Phase 3 reconciliation reads this mart joined with the
-- should-have-fired ledger to evaluate whether suppressed or
-- reduced-confidence signals would have been correct.
--
-- result_type buckets the raw Statcast `events` strings into a closed
-- set of categories that the ledger's correctness heuristic can reason
-- about. Anything Statcast emits outside the named buckets falls into
-- 'other' rather than dropping the row — losing at-bats silently would
-- bias the correction rate downstream.

WITH at_bat_events AS (
    SELECT
        game_pk,
        at_bat_number,
        pitcher_id,
        batter_id,
        inning,
        inning_topbot,
        events,
        event_time,
        -- The at-bat-ending pitch is the one with the highest pitch_number
        -- inside the at_bat that has a non-null `events`. We rank to pick it.
        ROW_NUMBER() OVER (
            PARTITION BY game_pk, at_bat_number
            ORDER BY pitch_number DESC
        ) AS pitch_rank
    FROM {{ ref("silver_pitch_events") }}
    WHERE events IS NOT NULL
        AND NOT is_duplicate
)

SELECT
    game_pk,
    at_bat_number,
    pitcher_id,
    batter_id,
    inning,
    inning_topbot,
    events AS raw_event,
    CASE
        WHEN events ILIKE '%strikeout%' THEN 'strikeout'
        WHEN events ILIKE '%walk%' AND events NOT ILIKE '%intent%' THEN 'walk'
        WHEN events ILIKE '%intent_walk%' OR events ILIKE '%intentional_walk%' THEN 'walk'
        WHEN events = 'single' THEN 'single'
        WHEN events = 'double' THEN 'double'
        WHEN events = 'triple' THEN 'triple'
        WHEN events = 'home_run' THEN 'home_run'
        WHEN events ILIKE '%hit_by_pitch%' THEN 'hit_by_pitch'
        WHEN events ILIKE '%ground%out%' OR events ILIKE '%force_out%' OR events ILIKE '%grounded_into_double_play%' THEN 'ground_out'
        WHEN events ILIKE '%fly%out%' OR events ILIKE '%pop_out%' OR events ILIKE '%sac_fly%' THEN 'fly_out'
        WHEN events = 'field_out' THEN 'fly_out'
        ELSE 'other'
    END AS result_type,
    event_time AS at_bat_end_time,
    CURRENT_TIMESTAMP AS computed_at
FROM at_bat_events
WHERE pitch_rank = 1
