# Leverage job

Live leverage index, updated on every count, base, or score change.

## Status

Not implemented. Phase 1.

## Signal definition

Tango-style Leverage Index: ratio of the change in win probability at the
current game state vs the average change across all states. Reference table
is precomputed from historical data and broadcast to the job at startup.

The streaming version is **provisional**. It uses the current pitcher and the
currently-due batter. If the batting team makes a pinch-hit or double-switch,
the batch recomputation supersedes the streaming value. The reconciliation
layer is where that delta becomes visible.

## State

- Key: `game_pk`
- `ValueState<GameContext>`:
  - inning, top/bot, outs
  - bases occupied
  - home_score, away_score
  - last_published_leverage
- Broadcast state: LI lookup table, ~24 states × 2 innings × some score-diff bins.

## Emissions

On any transition of the keyed state, emit:
- leverage_index (float)
- win_prob_home
- score_differential
- confidence: how many recent state transitions were late-arriving
