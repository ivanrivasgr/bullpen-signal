{{ config(materialized="table") }}

-- Per-pitch Leverage Index, joined from Tom Tango's published LI table
-- (the leverage_index_tango seed). Leverage is a property of the game state
-- alone -- inning, half, base-out state, and score differential -- not of the
-- pitcher or the pitch. See ADR 0026.
--
-- The game state on each pitch is mapped to Tango's table key and joined.
-- Three clamps align the live game with the table's domain:
--   - inning is capped at 9 (extra innings use the 9th-inning row, the table's
--     terminal leverage profile),
--   - score_diff is the home-team margin (home_score - away_score) clamped to
--     [-4, +4] (Tango's columns; blowouts beyond that share the boundary LI),
--   - base occupancy is taken from the runner-id columns being non-null.
--
-- This is computed identically for the streaming-as-of-emission and the
-- canonical post-game reads: leverage depends only on the game state carried on
-- the event, so the two reads diverge only where a correction changed that
-- state. That divergence is what the reconciliation surfaces (ADR 0001, D4).

WITH pitch_state AS (
    SELECT
        game_pk,
        at_bat_number,
        pitch_number,
        event_time,
        pitcher_id,
        batter_id,
        LEAST(inning, 9) AS li_inning,
        LOWER(inning_topbot) AS li_half,
        CASE WHEN on_1b IS NOT NULL THEN 1 ELSE 0 END AS li_on_1b,
        CASE WHEN on_2b IS NOT NULL THEN 1 ELSE 0 END AS li_on_2b,
        CASE WHEN on_3b IS NOT NULL THEN 1 ELSE 0 END AS li_on_3b,
        outs_when_up AS li_outs,
        GREATEST(-4, LEAST(4, home_score - away_score)) AS li_score_diff,
        is_late_arrival,
        is_duplicate
    FROM {{ ref("silver_pitch_events") }}
)

SELECT
    ps.game_pk,
    ps.at_bat_number,
    ps.pitch_number,
    ps.event_time,
    ps.pitcher_id,
    ps.batter_id,
    ps.li_inning AS inning_clamped,
    ps.li_half AS half_inning,
    ps.li_on_1b AS on_1b,
    ps.li_on_2b AS on_2b,
    ps.li_on_3b AS on_3b,
    ps.li_outs AS outs,
    ps.li_score_diff AS score_diff,
    li.leverage_index,
    ps.is_late_arrival,
    ps.is_duplicate
FROM pitch_state AS ps
LEFT JOIN {{ ref("leverage_index_tango") }} AS li
    ON ps.li_inning = li.inning
    AND ps.li_half = li.half_inning
    AND ps.li_on_1b = li.on_1b
    AND ps.li_on_2b = li.on_2b
    AND ps.li_on_3b = li.on_3b
    AND ps.li_outs = li.outs
    AND ps.li_score_diff = li.score_diff
