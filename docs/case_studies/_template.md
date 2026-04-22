# Case study: [short title]

- **Game:** game_pk
- **Date replayed:** YYYY-MM-DD
- **Signals involved:** fatigue / leverage / matchup / composite
- **Iceberg snapshots:**
  - bronze: `snapshot_id`
  - gold: `snapshot_id`

## Situation

One paragraph setting the scene: inning, score, base-out state, pitcher's
line so far. What a manager would have been weighing in that moment.

## What streaming said

- Alert emitted at: `event_time`
- Severity: info / warning / action
- Score: x.xx vs threshold y.yy
- Rationale from the alert record

## What batch ultimately said

- Canonical value at the same game state: x.xx
- Delta: ±
- Classification: confirmed / confirmed_late / reversed / softened / escalated

## Why the delta

The actual reason the two paths disagreed (or did not). Was it a late
arrival? A correction? A split that was too small at streaming time? State
the mechanism, not a vague "streaming was provisional".

## What a manager would have done

The operational consequence. Did the real-time window close? Would the
canonical truth have arrived in time?

## Queries

```sql
-- Paste the actual reconciliation queries used to produce the numbers
-- above. Anyone cloning the repo at the pinned snapshot should be able
-- to reproduce them.
```
