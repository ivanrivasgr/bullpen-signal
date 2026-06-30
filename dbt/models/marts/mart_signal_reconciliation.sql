{{ config(materialized="table") }}

-- The dashboard's reconciliation table, one row per alert per component signal:
-- (alert_uid, signal, streaming_value, canonical_value, delta, classification).
-- For each alert from mart_alerts, this brings the streaming and canonical
-- values of its three component signals (leverage, fatigue, matchup) from
-- mart_signal_values_long at the alert's pitch, takes the delta, and classifies
-- it per ADR 0026 D6.
--
-- Classification (D6), with relative-magnitude band T = 0.10:
--   reversed       : canonical flips the sign of streaming (both non-zero)
--   softened       : same sign, canonical magnitude below streaming by > T
--   escalated      : same sign, canonical magnitude above streaming by > T
--   confirmed_late : would be confirmed, but the pitch carried a late arrival
--   confirmed      : same sign, magnitude change within T
--
-- Leverage and fatigue have streaming == canonical (ADR 0026 D4), so they
-- classify as confirmed (or confirmed_late on a late-arrival pitch). Matchup is
-- where real divergence appears, so softened / escalated / reversed land there.

WITH alert_pitches AS (
    SELECT
        alert_uid,
        game_pk,
        at_bat_number,
        pitch_number,
        emitted_time,
        severity
    FROM {{ ref("mart_alerts") }}
),

-- Each alert joins to ALL three signals at its pitch -- the component signals
-- the reconciliation reports per alert.
joined AS (
    SELECT
        a.alert_uid,
        a.severity,
        a.emitted_time,
        v.signal,
        v.streaming_value,
        v.canonical_value,
        v.is_late_arrival,
        (v.streaming_value - v.canonical_value) AS delta
    FROM alert_pitches AS a
    JOIN {{ ref("mart_signal_values_long") }} AS v
        ON a.game_pk = v.game_pk
        AND a.at_bat_number = v.at_bat_number
        AND a.pitch_number = v.pitch_number
    WHERE v.streaming_value IS NOT NULL
      AND v.canonical_value IS NOT NULL
),

classified AS (
    SELECT
        alert_uid,
        signal,
        streaming_value,
        canonical_value,
        delta,
        severity,
        emitted_time,
        CASE
            -- reversed: the canonical value flips the sign (both non-zero).
            WHEN streaming_value <> 0 AND canonical_value <> 0
                 AND SIGN(streaming_value) <> SIGN(canonical_value)
                THEN 'reversed'
            -- softened: same sign, canonical magnitude below streaming beyond T.
            WHEN SIGN(streaming_value) = SIGN(canonical_value)
                 AND ABS(canonical_value) < ABS(streaming_value) * (1 - 0.10)
                THEN 'softened'
            -- escalated: same sign, canonical magnitude above streaming beyond T.
            WHEN SIGN(streaming_value) = SIGN(canonical_value)
                 AND ABS(canonical_value) > ABS(streaming_value) * (1 + 0.10)
                THEN 'escalated'
            -- confirmed_late: within T, but the pitch was a late arrival.
            WHEN is_late_arrival
                THEN 'confirmed_late'
            -- confirmed: same sign, magnitude change within T.
            ELSE 'confirmed'
        END AS classification
    FROM joined
)

SELECT
    alert_uid,
    signal,
    ROUND(streaming_value, 4) AS streaming_value,
    ROUND(canonical_value, 4) AS canonical_value,
    ROUND(delta, 4) AS delta,
    classification,
    severity,
    emitted_time
FROM classified
