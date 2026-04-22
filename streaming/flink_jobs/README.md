# Flink jobs

Stateful stream-processing jobs. Each subdirectory is one logical job with
its own state, its own sink, and its own tests.

## Design choices

- **PyFlink, not Java.** Phase 0 priority is shipping. PyFlink covers the
  DataStream and Table APIs we need. If a specific performance bottleneck
  justifies Java later, we port that one job.
- **Event time always.** Every source uses `event_time` from the payload and a
  watermark strategy tuned per signal. Processing time is disallowed.
- **Exactly-once.** Kafka source with `EXACTLY_ONCE` checkpointing, Iceberg or
  Kafka sink with transactional writes.
- **State in RocksDB.** Checkpoints to the shared `flink-checkpoints` volume
  in local dev, to S3 in cloud.

## Jobs

| Job | What it does | State shape |
|---|---|---|
| `fatigue` | Per-pitcher fatigue score, emitted every N pitches | `ValueState<PitcherState>` keyed by `pitcher_id` within `game_pk` |
| `leverage` | Live leverage index on every game-state change | `ValueState<GameContext>` keyed by `game_pk` |
| `matchup` | Expected wOBA vs next confirmed batter | Side-input of season splits, keyed join on `pitcher_id` |
| `alert_orchestrator` | Combine the three signals into severity-banded alerts | `MapState` of recent scores per pitcher |

## Running

Phase 1 work. Today the directories hold specs, not runnable jobs.
