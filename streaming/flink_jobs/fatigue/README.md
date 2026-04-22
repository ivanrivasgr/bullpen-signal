# Fatigue job

Computes a per-pitcher fatigue score in real time and emits updates to
`features.fatigue.v1`.

## Status

Not implemented. Phase 1.

## Signal definition

Weighted combination of:

1. **Pitch count** — absolute and relative to the pitcher's season baseline.
2. **Velocity delta** — rolling mean release speed vs the pitcher's first-20-pitch average of the game.
3. **Spin rate delta** — rolling mean spin rate vs season baseline for the pitcher and pitch type.
4. **Pace** — seconds between pitches, trend within the last 10 pitches.
5. **Command drop** — combined zone% and edge% over the last 15 pitches vs baseline.

Weights are fit once from the batch side against an observable target:
**the pitcher was removed within the next two batters and the removal was
performance-driven** (not double-switch, not planned bullpen day, not injury).
That label comes from a dbt model in `batch/dbt_project/models/intermediate/`
and is the reason this whole project has a defensible training signal.

## State

- Key: `(game_pk, pitcher_id)`
- `ValueState<PitcherGameState>` holding:
  - pitch_count
  - rolling window of last 20 release_speeds
  - rolling window of last 20 spin_rates
  - rolling window of last 10 pace_seconds
  - rolling window of last 15 zone-or-edge flags
  - pitch_type histogram
  - last_emitted_score

## Watermarks

Bounded out-of-orderness of 5 minutes. Late events beyond the watermark go to
a side output that feeds `features.fatigue.late.v1` for reconciliation.

## Emissions

One record per pitcher per pitch, with the fatigue score and its component
sub-scores so downstream can explain a threshold crossing.

## Testing

- Unit tests on the sub-score calculators, using synthetic rolling windows.
- Integration test: the replay engine feeding a known fatigue arc, asserting
  the score curve matches a golden series.
