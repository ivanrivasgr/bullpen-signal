{{ config(materialized="table") }}

-- Batch alert orchestrator: composes the three signals into pitcher-removal
-- alerts, per ADR 0026 D5 (batch is sufficient for a completed-game
-- reconciliation; live alerting is a separate concern).
--
-- The composition follows the decision a club actually makes about removing a
-- starter, as the literature frames it. Three factors drive it, and we have a
-- real signal for each:
--   1. Pitcher decline -- the fatigue signal (Mahalanobis deviation from the
--      pitcher's fresh baseline; silver_fatigue_signal).
--   2. Situation -- the Leverage Index (Tango; silver_leverage_index). Pulling a
--      non-ace in a high-leverage spot after several innings is worth up to a
--      win a season (Baseball Prospectus, "quick hooks").
--   3. Familiarity -- the times-through-the-order penalty: hitters gain ~10-15
--      points of wOBA each pass through the lineup (Tango et al. 2007; SABR).
--
-- We treat decline as CONTINUOUS rather than imposing a hard third-time-through
-- cutoff, following Brill et al. (2023), who find expected wOBA rises steadily
-- through the game with no sharp discontinuity at the 3rd TTO and recommend
-- basing removal on continuous decline, not a fixed cutoff. So the composite is
-- a continuous product of the three factors, and severity comes from where that
-- composite falls -- no special-cased inning or TTO number.
--
-- Thresholds are anchored to published references, not invented: leverage uses
-- Tango's bands (medium >= 0.85, high >= 2.0) and fatigue uses the 90th/95th
-- percentile cuts (the 95th is the mechanical-outlier threshold from the fatigue
-- paper, Dillon et al. 2025). See ADR 0026 D6.

WITH tto AS (
    -- Times through the order for each pitch: how many distinct batters the
    -- pitcher has faced so far in the game, divided by lineup size (9), gives
    -- the pass number. at_bat_number is sequential per game.
    SELECT
        game_pk,
        at_bat_number,
        pitch_number,
        pitcher_id,
        DENSE_RANK() OVER (
            PARTITION BY game_pk, pitcher_id ORDER BY at_bat_number
        ) AS batters_faced_so_far
    FROM {{ ref("silver_pitch_events") }}
    WHERE is_duplicate IS NOT TRUE
),

tto_factor AS (
    SELECT
        game_pk, at_bat_number, pitch_number, pitcher_id,
        -- pass through the order, 1-based; the TTO penalty grows with it.
        1.0 + (batters_faced_so_far - 1) / 9.0 AS times_through_order
    FROM tto
),

-- The canonical value of each signal at each pitch, pivoted wide so the
-- composite can read all three at once.
signals_wide AS (
    SELECT
        game_pk, at_bat_number, pitch_number,
        MAX(CASE WHEN signal = 'leverage' THEN canonical_value END) AS leverage,
        MAX(CASE WHEN signal = 'fatigue' THEN canonical_value END) AS fatigue,
        MAX(CASE WHEN signal = 'matchup' THEN canonical_value END) AS matchup
    FROM {{ ref("mart_signal_values_long") }}
    GROUP BY game_pk, at_bat_number, pitch_number
),

composed AS (
    SELECT
        s.game_pk,
        s.at_bat_number,
        s.pitch_number,
        pe.pitcher_id,
        pe.event_time,
        s.leverage,
        s.fatigue,
        s.matchup,
        t.times_through_order,
        -- Continuous composite. Each factor normalized to a roughly 0-1+ scale
        -- by its reference, then multiplied: decline (fatigue / its 95th-pct
        -- outlier cut of ~4.0), situation (leverage / Tango's high band of 2.0),
        -- familiarity (TTO penalty, growing past the 2nd pass). The product is
        -- high only when the pitcher is declining AND the spot matters AND the
        -- order has turned over -- the conjunction a manager acts on.
        (COALESCE(s.fatigue, 0) / 4.0)
            * (COALESCE(s.leverage, 0) / 2.0)
            * GREATEST(1.0, t.times_through_order - 1.0) AS composite_score
    FROM signals_wide AS s
    JOIN tto_factor AS t
        ON s.game_pk = t.game_pk
        AND s.at_bat_number = t.at_bat_number
        AND s.pitch_number = t.pitch_number
    JOIN {{ ref("silver_pitch_events") }} AS pe
        ON s.game_pk = pe.game_pk
        AND s.at_bat_number = pe.at_bat_number
        AND s.pitch_number = pe.pitch_number
    WHERE pe.is_duplicate IS NOT TRUE
),

classified AS (
    SELECT
        *,
        CASE
            -- action: declining (fatigue past the 95th-pct outlier cut) in a
            -- high-leverage spot (Tango high band) with the order turned over.
            WHEN fatigue >= 4.0 AND leverage >= 2.0 AND times_through_order >= 2.0
                THEN 'action'
            -- warning: a mechanical outlier (95th pct) in a spot that matters.
            WHEN fatigue >= 4.0 AND leverage >= 0.85
                THEN 'warning'
            -- info: early decline (90th pct) in a spot that matters.
            WHEN fatigue >= 3.2 AND leverage >= 0.85
                THEN 'info'
            ELSE NULL
        END AS severity
    FROM composed
)

SELECT
    -- Stable alert id from the pitch identity and severity.
    severity || ':' || CAST(game_pk AS VARCHAR) || ':' || CAST(at_bat_number AS VARCHAR)
        || ':' || CAST(pitch_number AS VARCHAR) AS alert_uid,
    game_pk,
    at_bat_number,
    pitch_number,
    pitcher_id,
    event_time AS emitted_time,
    severity,
    ROUND(composite_score, 3) AS composite_score,
    CASE severity
        WHEN 'action' THEN 1.0
        WHEN 'warning' THEN 0.5
        WHEN 'info' THEN 0.25
    END AS threshold,
    leverage,
    fatigue,
    matchup,
    ROUND(times_through_order, 2) AS times_through_order
FROM classified
WHERE severity IS NOT NULL
