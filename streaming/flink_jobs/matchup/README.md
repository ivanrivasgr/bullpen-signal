# Matchup job

Expected wOBA of the active pitcher versus the next confirmed batter.

## Status

Not implemented. Phase 1.

## Signal definition

For the current pitcher and the next confirmed batter:

1. Pull pitcher's pitch-mix probabilities by count and batter handedness (season-to-date).
2. Pull batter's xwOBA by pitch type and handedness (season-to-date).
3. Weighted sum: `sum_i P(pitch_i | count, BvP handedness) * xwOBA(batter, pitch_i, handedness)`.
4. Adjust by park factor broadcast at startup.

Streaming uses season-to-date splits as of the replay clock. Batch uses
season totals plus park adjustments plus batted-ball regression.

The interesting deltas appear in two places:
- Early season, when splits are small-sample and streaming overreacts.
- After a pitcher injury or role change, when the historical mix stops being predictive.

## State

- Key: `pitcher_id`
- Side input: batter splits, refreshed hourly from the gold mart.
- `ValueState<MatchupState>` holding rolling pitch-mix counts for the current game.

## Emissions

- matchup_edge (float): expected wOBA allowed vs the league baseline.
- recommendation: KEEP | WARM | REPLACE with a confidence.
- top_contributing_pitch_type: for explainability.
