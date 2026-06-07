{{
    config(
        materialized="table",
    )
}}

-- mart_reconciliation_summary
--
-- Aggregates mart_should_have_fired_ledger by the three dimensions
-- Phase 3 reconciliation needs to evaluate the system's holding-back
-- decisions: lineup_state at emission (per ADR 0013), confidence_band
-- (per ADR 0016), and handedness_matchup (the matchup primitive).
--
-- For each group, the mart reports:
--   - total_pitches: how many signals fell into this bucket
--   - evaluable_pitches: how many had a non-NULL would_have_been_correct
--   - would_have_been_correct_count: TRUE rows
--   - would_have_been_missed_count: FALSE rows
--   - null_count: pitches where outcome was unknown or signal was neutral
--   - correction_rate: would_have_been_correct_count / evaluable_pitches
--     (NULL when evaluable_pitches = 0 — undefined, not zero)
--
-- The correction_rate uses the heuristic defined in ADR 0018. It is not
-- a calibrated metric. Reading 0.65 here does not mean "65% accuracy" —
-- it means "of the held-back decisions where we could evaluate against
-- realized outcomes, 65% pointed the right direction by sign."
--
-- Why three dimensions and not more:
--   - lineup_state separates BATTER_UNCERTAIN-window pitches from
--     projected-batter pitches, which have different failure modes.
--   - confidence_band separates the two non-full bands. Phase 3 wants
--     to know whether reduced and suppressed signals correct at
--     different rates.
--   - handedness_matchup is the first-order driver of signal_value
--     today (placeholders are keyed off it). Aggregating by matchup
--     lets the future calibration step replace each placeholder with
--     the observed correction rate at that handedness combination.
--
-- This mart is empty until BATTER_UNCERTAIN replays populate the
-- ledger with reduced/suppressed signals. The shape is ready; the
-- data accumulates over the calibration window Phase 3 will define.

WITH ledger_with_matchup AS (
    SELECT
        l.game_pk,
        l.at_bat_number,
        l.pitch_number,
        l.confidence_band,
        l.lineup_state_at_emission,
        l.would_have_been_correct,
        sme.handedness_matchup
    FROM {{ ref("mart_should_have_fired_ledger") }} AS l
    LEFT JOIN {{ ref("silver_matchup_events") }} AS sme
        ON l.game_pk = sme.game_pk
        AND l.at_bat_number = sme.at_bat_number
        AND l.pitch_number = sme.pitch_number
)

SELECT
    lineup_state_at_emission,
    confidence_band,
    handedness_matchup,
    COUNT(*) AS total_pitches,
    SUM(CASE WHEN would_have_been_correct IS NOT NULL THEN 1 ELSE 0 END) AS evaluable_pitches,
    SUM(CASE WHEN would_have_been_correct = TRUE THEN 1 ELSE 0 END) AS would_have_been_correct_count,
    SUM(CASE WHEN would_have_been_correct = FALSE THEN 1 ELSE 0 END) AS would_have_been_missed_count,
    SUM(CASE WHEN would_have_been_correct IS NULL THEN 1 ELSE 0 END) AS null_count,
    -- Correction rate is undefined (NULL) when there are zero evaluable
    -- rows in the group. Reporting 0.0 in that case would mislead
    -- consumers into reading "no corrections" when the truth is "no
    -- data to evaluate."
    CASE
        WHEN SUM(CASE WHEN would_have_been_correct IS NOT NULL THEN 1 ELSE 0 END) > 0
            THEN CAST(SUM(CASE WHEN would_have_been_correct = TRUE THEN 1 ELSE 0 END) AS DOUBLE)
                 / SUM(CASE WHEN would_have_been_correct IS NOT NULL THEN 1 ELSE 0 END)
        ELSE NULL
    END AS correction_rate,
    CURRENT_TIMESTAMP AS computed_at
FROM ledger_with_matchup
GROUP BY lineup_state_at_emission, confidence_band, handedness_matchup
