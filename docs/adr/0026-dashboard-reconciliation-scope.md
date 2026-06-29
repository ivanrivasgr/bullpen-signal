# ADR 0026 — Dashboard Reconciliation: Scope, Signals, and Method

- **Status:** Accepted
- **Date:** 2026-06-26

## Context

The dashboard (`apps/dashboard/main.py`) renders a reconciliation table grouped
by alert, across three signals — leverage, fatigue, matchup — each showing the
streaming value against the batch-canonical value, with a delta and a
classification. It currently renders against `synthetic_data.py`.

Connecting it to real data is not a wiring task. The dashboard displays three
signals; only matchup exists. There is no leverage signal, no per-pitch fatigue
signal, no alert orchestrator, and no per-alert reconciliation mart. Those have
to be built.

The governing constraint is the separation of result from process. The dashboard
defines the *result*: the shape of what is shown. The *process* that produces the
numbers must be of the standard a major-league club would accept, not the toy
formulas the synthetic narrative uses to tell a clean story. The synthetic
fatigue is an invented weighting; the synthetic leverage is an invented curve
(`0.8 + pitch_idx/200`); the synthetic matchup is derived arithmetically from
that fatigue. None of those is how the quantity is actually computed. This ADR
fixes the real method for each signal before anything is built.

## Decisions

### D1 — Leverage: real Leverage Index

Leverage is the Leverage Index (Tom Tango's measure of how much the game state
swings with the next event), derived from the game state already present in
`silver_pitch_events`: inning, half-inning, outs, base-out state
(on_1b/on_2b/on_3b), and score differential. A published LI reference table is
carried as a seed and documented as the source. This replaces the synthetic
curve. LI is the industry-standard leverage quantity; deriving it from observed
game state is verifiable and reproducible.

### D2 — Fatigue: real per-pitch signal

Fatigue is a per-pitch signal built from rolling deltas of velocity, spin, and
command against the pitcher's own in-game baseline (the first N pitches), with
the velocity, spin, and command components kept separate as the dashboard shows
them. This replaces both the synthetic weighting and the existing
`silver_pitcher_game_fatigue`, which is a per-game aggregate bucketed by pitch
count and cannot state fatigue at a specific pitch.

### D3 — Matchup: the existing signal

Matchup is the signal already built and verified: `streaming.matchup_signals`
against `silver_matchup_signals`. No change.

### D4 — What reconciliation means for each signal

All three signals are computed by shared core logic. The streaming value is
computed from data as of emission (projected lineup, partial in-game history);
the canonical value is computed post-game from complete, corrected data
(late-arrivals reconciled, corrections applied). The delta is therefore the
effect of late-arriving data and corrections — the same thesis ADR 0001 states,
applied uniformly to all three signals. No signal fabricates a streaming value
that was never computed; where a signal has no separate streaming computation,
that is stated, not faked.

### D5 — Alert orchestrator: batch

Alerts are composed in batch (`mart_alerts`) over the signal values. The
dashboard shows the reconciliation of a completed game, which does not require
real-time alerting. A streaming orchestrator is a separate concern and out of
scope here.

### D6 — Classification thresholds

With streaming value `s`, canonical value `c`, and relative-magnitude band
`T = 0.10`:

- `reversed`: `sign(s) != sign(c)`, both non-zero.
- `softened`: same sign, `abs(c) < abs(s) * (1 - T)`.
- `escalated`: same sign, `abs(c) > abs(s) * (1 + T)`.
- `confirmed`: same sign, magnitude change within `T`.
- `confirmed_late`: would be `confirmed`, but the pitch carried `is_late_arrival`.

These are exactly the five classes the dashboard's CSS defines.

## Consequences

The dashboard milestone is a sequence of marts plus a `real_data.py`: leverage
signal, per-pitch fatigue signal, a unified long signal table, a batch alert
orchestrator, and the per-alert reconciliation mart, then the data module and the
import swap. Each signal is derived from a verifiable source, not a narrative
formula, so the numbers the dashboard shows mean what a club would expect them to
mean — subject to the separate, already-registered work of calibrating the
placeholder magnitudes (ADR 0016) over full-season volume.
