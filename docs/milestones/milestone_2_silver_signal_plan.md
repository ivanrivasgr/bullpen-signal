# Milestone 2 - Silver Layer And Initial Fatigue Signal

## Goal

Milestone 2 turns the verified bronze lakehouse foundation into the first
reproducible analytical signal.

The target path is:

```text
bronze.pitches
  -> silver.pitch_events
  -> silver.pitcher_game_fatigue

```

`silver.pitch_events` normalizes pitch-level rows for analytical use.
`silver.pitcher_game_fatigue` adds the first workload-based fatigue indicator
at game/pitcher grain.

## Non-Goals

This milestone does not deliver:

- a dashboard
- an alert orchestrator
- a machine learning model
- matchup modeling
- rolling state per pitch
- live streaming fatigue computation
- public claims about a predictive system

## Silver Pitch Events

`silver.pitch_events` is the normalized pitch-level analytical table derived
from `bronze.pitches`.

Expected columns:

- pitch_id
- event_time
- event_day
- game_pk
- at_bat_number
- pitch_number
- inning
- inning_topbot
- pitcher_id
- batter_id
- pitch_type
- release_speed
- release_spin_rate
- plate_x
- plate_z
- zone
- balls
- strikes
- outs_when_up
- on_1b
- on_2b
- on_3b
- home_score
- away_score
- description
- events
- is_late_arrival
- is_duplicate
- correction_of
- ingestion_time
- kafka_partition
- source_offset

The replay-engine provenance flags are preserved intact. Silver does not filter
late arrivals, duplicates, or corrections. Downstream consumers decide whether
to filter them for a specific signal.

## Pitcher Game Fatigue

`silver.pitcher_game_fatigue` is the first analytical feature table.

Grain:

```text
one row per (game_pk, pitcher_id)
```

Expected columns:

- game_pk
- pitcher_id
- first_pitch_time
- last_pitch_time
- pitch_count
- max_inning
- avg_release_speed
- avg_release_spin_rate
- fatigue_bucket
- computed_at

This table filters duplicate pitches before aggregation because pitch count is
a workload measure. That filter belongs in the fatigue feature, not in
`silver.pitch_events`.

## Initial Fatigue Thresholds

Initial fatigue buckets:

- `low`: fewer than 25 pitches
- `medium`: 25 to 49 pitches
- `high`: 50 or more pitches

These thresholds are placeholders. Their operating-point validity is not
assumed - it will be probed in the synthetic stationarity exercise documented
in `docs/external_commitments.md` (entry dated 2026-04-29). The probe will
compare activation rates across two Statcast windows with different
roster-churn profiles. If the probe finds the operating point drifts
materially, the thresholds will be revisited as part of governance work, not
as a tuning exercise.

## Downstream Dependencies

The stationarity mini-probe scheduled for 2026-05-18 through 2026-05-22
depends directly on `silver.pitcher_game_fatigue`.

That probe will consume this table to compare fatigue-bucket activation rates
across two historical Statcast windows with different roster-churn profiles.
Milestone 2 does not run the probe. It makes the table stable enough that the
probe can run without re-architecting the silver layer.

## Quality Bar

Milestone 2 is complete only when:

- silver schemas are defined as code
- silver tables can be created locally
- dbt project scaffolding exists and parses
- `silver.pitch_events` is built from `bronze.pitches`
- `silver.pitcher_game_fatigue` is built from `silver.pitch_events`
- unit tests validate schema and SQL contracts
- integration tests prove bronze -> silver output
- integration tests prove fatigue buckets for known synthetic pitchers
- demo queries return understandable results
- docs distinguish implemented behavior from future work

## Demo Query

```sql
SELECT
    game_pk,
    pitcher_id,
    pitch_count,
    avg_release_speed,
    fatigue_bucket
FROM silver_pitcher_game_fatigue
ORDER BY pitch_count DESC;
```
