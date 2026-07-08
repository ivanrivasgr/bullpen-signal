# Matchup job

Computes the handedness-matchup signal per pitch and writes it to the
`streaming.matchup_signals` Iceberg table. This is the streaming half of the
dual-path comparison: the value the real-time system produces under lineup
uncertainty, later reconciled against the batch-canonical value for the same
pitch.

## Current implementation

Reads pitch events from `pitches.raw` (Avro via the Schema Registry), derives
the pitcher-vs-batter handedness matchup, and emits the calibrated signal value
for that matchup. The job is stateless and row-wise — it never looks across
pitches — so a pitch's signal depends only on that pitch's own fields.

Under lineup uncertainty a pitch expands into two emissions (ADR 0020): a
reduced-confidence value from the projected batter, tagged `uncertain`, and a
full-confidence value from the confirmed batter, tagged `confirmed`. The
expansion is driven by `plan_signal_emissions` and the per-emission value by
`compute_signal_fields`, both in `signals/matchup_core.py` — the same core the
batch path calls, so the two paths cannot drift.

- **Source:** `pitches.raw` (Kafka, Confluent-framed Avro).
- **Sink:** `streaming.matchup_signals` (Iceberg REST catalog on MinIO).
- **Signal magnitudes:** `signals/matchup_calibration.py`, calibrated from the
  2024 season with the delta method (ADR 0027).

The signal value, the confidence band, and the emission plan all come from
`signals/matchup_core.py`. The Flink job wires that core into a `LATERAL TABLE`
emission UDTF and a StatementSet insert; it holds no analytics logic of its own.
That is the anti-drift guarantee of ADR 0001 and ADR 0021.

## Planned evolution — a full expected-wOBA matchup

The handedness signal is the calibrated first version. The next iteration
replaces it with an expected-wOBA computation over the pitcher's pitch mix, for
the current pitcher versus the next confirmed batter:

1. Pull the pitcher's pitch-mix probabilities by count and batter handedness (season-to-date).
2. Pull the batter's xwOBA by pitch type and handedness (season-to-date).
3. Weighted sum: `sum_i P(pitch_i | count, BvP handedness) * xwOBA(batter, pitch_i, handedness)`.
4. Adjust by park factor broadcast at startup.

Streaming would use season-to-date splits as of the replay clock; batch would
use season totals plus park adjustments plus batted-ball regression. The
interesting deltas would appear in two places: early season, when splits are
small-sample and streaming overreacts; and after a pitcher injury or role
change, when the historical mix stops being predictive.

This makes the job stateful:

- Key: `pitcher_id`
- Side input: batter splits, refreshed hourly from the gold mart.
- `ValueState<MatchupState>` holding rolling pitch-mix counts for the current game.

Emissions would extend to: `matchup_edge` (expected wOBA allowed vs the league
baseline), a `KEEP | WARM | REPLACE` recommendation with a confidence, and
`top_contributing_pitch_type` for explainability.
