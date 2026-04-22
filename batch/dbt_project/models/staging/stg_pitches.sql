{{
  config(
    materialized='view'
  )
}}

-- Dedupe and apply corrections. One row per canonical pitch.
--
-- Dedup rule: on (game_pk, at_bat_number, pitch_number), keep the most
-- recent non-duplicate event by ingest_time. Corrections are applied as a
-- left join on original_pitch_uid; the corrected field wins.

with raw as (
    select *
    from {{ source('bronze', 'pitches') }}
    where is_duplicate = false
),

dedup as (
    select *
    from (
        select
            *,
            row_number() over (
                partition by game_pk, at_bat_number, pitch_number
                order by ingest_time desc
            ) as rn
        from raw
    )
    where rn = 1
),

corrections as (
    select
        original_pitch_uid,
        field,
        new_value,
        row_number() over (
            partition by original_pitch_uid, field
            order by ingest_time desc
        ) as rn
    from {{ source('bronze', 'corrections') }}
),

latest_corrections as (
    select original_pitch_uid, field, new_value
    from corrections
    where rn = 1
)

select
    d.event_time,
    d.ingest_time,
    d.game_pk,
    d.at_bat_number,
    d.pitch_number,
    d.inning,
    d.inning_topbot,
    d.pitcher_id,
    d.batter_id,
    coalesce(
        (select new_value from latest_corrections c
         where c.original_pitch_uid = cast(d.game_pk as varchar) || ':' ||
                                     cast(d.at_bat_number as varchar) || ':' ||
                                     cast(d.pitch_number as varchar)
           and c.field = 'pitch_type'),
        d.pitch_type
    ) as pitch_type,
    d.release_speed,
    d.release_spin_rate,
    d.plate_x,
    d.plate_z,
    d.zone,
    d.balls,
    d.strikes,
    d.outs_when_up,
    d.on_1b,
    d.on_2b,
    d.on_3b,
    d.description,
    d.events,
    d.home_score,
    d.away_score
from dedup d
