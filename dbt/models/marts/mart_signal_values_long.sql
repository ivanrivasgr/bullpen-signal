{{ config(materialized="table") }}

-- One row per (pitch, signal), carrying the streaming value and the canonical
-- value side by side for each of the three dashboard signals: leverage,
-- fatigue, matchup. The per-signal delta the reconciliation reports is always
-- within one signal's own scale (streaming vs canonical of the SAME signal), so
-- the signals keep their native units -- leverage as Tango LI, fatigue as a
-- Mahalanobis distance, matchup as the handedness signal value. They are never
-- compared across signals, so no common normalization is needed.
--
-- Per ADR 0026 D4, leverage and fatigue depend only on the game state and the
-- pitch-tracking values carried on each event, so their streaming-as-of-emission
-- and canonical reads are the same computation: streaming_value = canonical_value,
-- and any delta arises only where a correction changed those inputs. Matchup is
-- the one signal with two genuinely distinct sources -- the streaming emission
-- under uncertainty vs the batch-canonical value -- so its streaming and
-- canonical values can differ. That difference is the divergence the
-- reconciliation exists to surface (ADR 0001).

WITH leverage AS (
    SELECT
        game_pk, at_bat_number, pitch_number,
        'leverage' AS signal,
        leverage_index AS streaming_value,
        leverage_index AS canonical_value,
        is_late_arrival
    FROM {{ ref("silver_leverage_index") }}
    WHERE leverage_index IS NOT NULL
),

fatigue AS (
    SELECT
        game_pk, at_bat_number, pitch_number,
        'fatigue' AS signal,
        fatigue AS streaming_value,
        fatigue AS canonical_value,
        is_late_arrival
    FROM {{ ref("silver_fatigue_signal") }}
    WHERE fatigue IS NOT NULL
),

-- Matchup: the streaming emission under uncertainty (the reduced-confidence
-- value the real-time path produced) against the batch-canonical value for the
-- same pitch. Both come from the shared matchup core; they differ when the
-- projected lineup the stream saw turned out wrong, which is the point.
matchup_streaming AS (
    SELECT
        game_pk, at_bat_number, pitch_number,
        signal_value AS streaming_value,
        is_late_arrival_flag AS is_late_arrival
    FROM (
        SELECT
            sms.game_pk, sms.at_bat_number, sms.pitch_number,
            sms.signal_value,
            FALSE AS is_late_arrival_flag,
            ROW_NUMBER() OVER (
                PARTITION BY sms.game_pk, sms.at_bat_number, sms.pitch_number
                ORDER BY CASE sms.lineup_state_at_emission
                    WHEN 'uncertain' THEN 0 ELSE 1 END
            ) AS rn
        FROM {{ source("streaming", "matchup_signals") }} AS sms
    )
    WHERE rn = 1
),

matchup_canonical AS (
    SELECT
        game_pk, at_bat_number, pitch_number,
        signal_value AS canonical_value
    FROM (
        SELECT
            game_pk, at_bat_number, pitch_number, signal_value,
            ROW_NUMBER() OVER (
                PARTITION BY game_pk, at_bat_number, pitch_number
                ORDER BY CASE lineup_state_at_emission
                    WHEN 'confirmed' THEN 0 ELSE 1 END
            ) AS rn
        FROM {{ ref("silver_matchup_signals") }}
    )
    WHERE rn = 1
),

matchup AS (
    SELECT
        COALESCE(s.game_pk, c.game_pk) AS game_pk,
        COALESCE(s.at_bat_number, c.at_bat_number) AS at_bat_number,
        COALESCE(s.pitch_number, c.pitch_number) AS pitch_number,
        'matchup' AS signal,
        s.streaming_value,
        c.canonical_value,
        COALESCE(s.is_late_arrival, FALSE) AS is_late_arrival
    FROM matchup_streaming AS s
    FULL OUTER JOIN matchup_canonical AS c
        ON s.game_pk = c.game_pk
        AND s.at_bat_number = c.at_bat_number
        AND s.pitch_number = c.pitch_number
)

SELECT game_pk, at_bat_number, pitch_number, signal,
       streaming_value, canonical_value, is_late_arrival
FROM leverage
UNION ALL
SELECT game_pk, at_bat_number, pitch_number, signal,
       streaming_value, canonical_value, is_late_arrival
FROM fatigue
UNION ALL
SELECT game_pk, at_bat_number, pitch_number, signal,
       streaming_value, canonical_value, is_late_arrival
FROM matchup
