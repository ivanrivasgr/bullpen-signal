{{
    config(
        materialized="table",
    )
}}

-- mart_should_have_fired_ledger
--
-- The ledger Chad named on 2026-05-19 as load-bearing for Phase 3
-- governance review. One row per pitch where the matchup signal was
-- emitted with confidence_band IN ('reduced', 'suppressed') — these
-- are the decisions the system did not commit to with full weight.
-- Each row is joined with the realized at-bat outcome from
-- mart_canonical_outcomes so reconciliation can answer the
-- "should we have fired" question retrospectively.
--
-- The reduced and suppressed signals read here come from the streaming
-- matchup signal table, not the batch model (ADR 0023): these are the
-- decisions the real-time path made under uncertainty, which is what the
-- "should we have fired" question evaluates. The batch model still
-- produces its own signals; the ledger evaluates the streaming path's.
--
-- would_have_been_correct is a heuristic, not a calibrated metric.
-- The matchup signal_value carried by the streaming signal is a
-- placeholder per ADR 0016 (the magnitudes encode handedness intuition
-- but are not calibrated against outcomes yet). The heuristic asks:
-- if the signal pointed toward the pitcher (positive signal_value) and
-- the at-bat resulted in a pitcher-favorable outcome (strikeout, weak
-- contact), the signal would have been correct. Mirror for batter-
-- favorable signals and outcomes. Neutral signals (signal_value = 0)
-- produce NULL, not false — there is no correctness claim to evaluate.
--
-- Phase 3 reconciliation will replace this heuristic with calibrated
-- correction rates once enough outcome data accumulates. The mart's
-- shape stays the same; only the would_have_been_correct definition
-- evolves.

WITH suppressed_or_reduced_signals AS (
    SELECT
        sms.game_pk,
        sms.at_bat_number,
        sms.pitch_number,
        sms.pitcher_id,
        sms.batter_id,
        sms.signal_value,
        sms.confidence_band,
        sms.lineup_state_at_emission,
        sms.event_time AS signal_event_time
    FROM {{ source("streaming", "matchup_signals") }} AS sms
    WHERE sms.confidence_band IN ('reduced', 'suppressed')
    -- The stream is delivered at-least-once: Kafka can hand the same event to
    -- the job more than once, so a byte-identical emission (same pitch, same
    -- event_time, same band, same value, same lineup state) can appear twice.
    -- That is one logical event delivered twice, not two facts, so we process
    -- it idempotently and keep one delivery. This is NOT a noise filter: a
    -- late arrival re-sends with a different event_time and is kept (it is a
    -- real observation the real-time path made at another moment), and the
    -- reduced/full double emission differs by band and is kept. Only exact
    -- redelivery of the same emission collapses.
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY
            sms.game_pk,
            sms.at_bat_number,
            sms.pitch_number,
            sms.event_time,
            sms.confidence_band,
            sms.signal_value,
            sms.lineup_state_at_emission
        ORDER BY sms.event_time
    ) = 1
),

with_outcomes AS (
    SELECT
        s.game_pk,
        s.at_bat_number,
        s.pitch_number,
        s.pitcher_id,
        s.batter_id,
        s.signal_value,
        s.confidence_band,
        s.lineup_state_at_emission,
        s.signal_event_time,
        o.result_type,
        o.at_bat_end_time
    FROM suppressed_or_reduced_signals AS s
    LEFT JOIN {{ ref("mart_canonical_outcomes") }} AS o
        ON s.game_pk = o.game_pk
        AND s.at_bat_number = o.at_bat_number
)

SELECT
    game_pk,
    at_bat_number,
    pitch_number,
    pitcher_id,
    batter_id,
    signal_value,
    confidence_band,
    lineup_state_at_emission,
    signal_event_time,
    result_type,
    at_bat_end_time,
    -- Heuristic correctness check. Documented as such; not a calibrated
    -- metric. See model header for the rationale and the Phase 3 plan
    -- to replace this with calibrated correction rates.
    CASE
        WHEN signal_value > 0
             AND result_type IN ('strikeout', 'ground_out', 'fly_out', 'other')
            THEN TRUE
        WHEN signal_value < 0
             AND result_type IN ('single', 'double', 'triple', 'home_run', 'walk', 'hit_by_pitch')
            THEN TRUE
        WHEN signal_value = 0
            THEN NULL
        WHEN result_type IS NULL
            THEN NULL  -- outcome not yet known; cannot evaluate
        ELSE FALSE
    END AS would_have_been_correct,
    CURRENT_TIMESTAMP AS computed_at
FROM with_outcomes
