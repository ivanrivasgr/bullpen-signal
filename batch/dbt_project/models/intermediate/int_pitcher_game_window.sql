{{
  config(
    materialized='incremental',
    incremental_strategy='merge',
    unique_key=['game_pk', 'pitcher_id', 'pitch_number']
  )
}}

-- Rolling state per pitcher within a game. This is the batch counterpart to
-- the Flink fatigue job's keyed state, used as the canonical truth for
-- reconciliation. Deltas between this and the streaming emissions are what
-- prove the thesis of the project.

with pitches as (
    select * from {{ ref('stg_pitches') }}
    {% if is_incremental() %}
    where event_time > (select coalesce(max(event_time), '1900-01-01') from {{ this }})
    {% endif %}
),

ordered as (
    select
        *,
        row_number() over (
            partition by game_pk, pitcher_id
            order by at_bat_number, pitch_number
        ) as game_pitch_idx
    from pitches
)

select
    event_time,
    game_pk,
    pitcher_id,
    at_bat_number,
    pitch_number,
    game_pitch_idx as pitches_thrown_so_far,
    avg(release_speed) over w_20 as velocity_last_20_avg,
    avg(release_spin_rate) over w_20 as spin_last_20_avg,
    -- First-20 baseline is stable inside a game; recomputed per row for simplicity.
    avg(case when game_pitch_idx <= 20 then release_speed end) over (
        partition by game_pk, pitcher_id
    ) as velocity_first_20_avg,
    avg(case when game_pitch_idx <= 20 then release_spin_rate end) over (
        partition by game_pk, pitcher_id
    ) as spin_first_20_avg
from ordered
window w_20 as (
    partition by game_pk, pitcher_id
    order by at_bat_number, pitch_number
    rows between 19 preceding and current row
)
