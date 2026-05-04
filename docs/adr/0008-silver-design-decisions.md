# ADR 0008 - Silver Design Decisions

- **Status:** Accepted
- **Date:** 2026-05-04

## Context

Milestone 1 established `bronze.pitches` as the durable landing table for
decoded pitch events. Milestone 2 needs the first analytical layer on top of
that table.

Three choices are load-bearing before implementation starts:

1. whether silver filters replay-engine audit flags
2. what grain the initial fatigue table uses
3. how to describe the first fatigue thresholds without overstating them

## Decision

Use the following silver design rules.

First, `silver.pitch_events` preserves replay-engine provenance intact:

- `is_late_arrival`
- `is_duplicate`
- `correction_of`
- `ingestion_time`
- `kafka_partition`
- `source_offset`

Silver does not filter duplicate rows, late arrivals, or corrections. Lineage is
part of the analytical table. Downstream consumers choose the filter policy for
their own signal.

Second, `silver.pitcher_game_fatigue` uses game/pitcher snapshot grain:

```text
one row per (game_pk, pitcher_id)
```

It is a batch feature table for the final state of the pitcher within a game.
It is not rolling per pitch.

Third, the initial fatigue thresholds are workload placeholders:

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

## Alternatives Considered

### Filter duplicate and late-arrival rows in silver

Rejected. Filtering in silver would erase the audit trail before downstream
signals can make their own policy choices.

### Rolling fatigue state per pitch

Rejected for Milestone 2. Rolling state belongs in a later streaming signal.
This milestone is focused on the batch silver path and a game-level snapshot.

### Treat initial thresholds as calibrated

Rejected. The numbers are useful for creating an observable signal, not for
claiming validated baseball meaning.

## Consequences

- `silver.pitch_events` remains closer to bronze than a curated mart would be.
- Fatigue aggregation filters `is_duplicate = false` inside the feature table,
  not in the shared pitch-events table.
- The stationarity mini-probe has a stable downstream table to consume.
- The project can discuss the first fatigue signal without claiming it is a
  trained model or predictive system.
