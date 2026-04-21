# Replay engine

Turns historical MLB data into a deterministic event stream. Reads Statcast
for the target date, enriches with MLB StatsAPI game-state info where
available, injects configurable noise (late arrivals, duplicates, official
corrections), and publishes to Kafka.

## Why this exists

Statcast and StatsAPI are batch-shaped: you fetch a day, a game, a team.
Flink needs a stream. The replay engine is the seam between them. Same
underlying ground truth goes into both the streaming path (Flink jobs) and the
batch path (dbt), which is what lets us measure their deltas.

## Usage

```bash
# smallest smoke test, no Kafka required
python -m ingestion.replay_engine.run --game-date 2024-06-15 --limit 20 --dry-run

# real replay of a single game at 10x
python -m ingestion.replay_engine.run --game-date 2024-06-15 --game-pk 745642 --speed 10

# a whole day at 60x
python -m ingestion.replay_engine.run --game-date 2024-06-15 --speed 60
```

## Caveats worth documenting

- **Event time is synthesized.** Statcast does not publish wall-clock per-pitch
  timestamps. We synthesize a monotonic `event_time` using a realistic pitch
  cadence (~23s between pitches, ~90s between at-bats). It is good enough for
  watermark and windowing tests, not for real-time pitch-tempo analysis.
- **StatsAPI is best-effort.** If the endpoint is slow or a game is in
  progress, enrichment degrades to empty. The Kafka stream still produces.
- **Corrections are simulated.** They model the shape of MLB revisions
  (pitch type flips, official scoring changes), not any specific historical
  correction. That is a deliberate choice: the proof is in how the system
  handles the class of events, not in replicating a particular incident.
- **Noise rates are knobs, not truth.** Tune via `.env`. The defaults are
  conservative; benchmarks should sweep them.

## What this does not do yet

- Avro wire format. Phase 1.
- Parallel game replay. Today, games within a date are replayed serially.
- StatsAPI-driven game-state events published to `game_state.raw`. Only the
  Statcast-derived pitches go out today. Adding game-state publishing is the
  next change.
