# Alert orchestrator

Combines the fatigue, leverage, and matchup signals into operationally useful
alerts. This is the job a manager (or a dashboard) actually consumes.

## Status

Not implemented. Phase 1.

## Why this is separate from the three feature jobs

The three feature jobs are independently testable and independently useful.
Mixing them into one job makes every change a big-bang deploy. Keeping
orchestration separate lets us tune thresholds, add new signals, or swap a
feature implementation without touching the other two.

## Severity bands

| Severity | Meaning | Example |
|---|---|---|
| `info` | Situational awareness | "Leverage is rising, heads up on the bullpen." |
| `warning` | Prep recommended | "Warm up a reliever; fatigue is elevated and the matchup tilts against." |
| `action` | Decision threshold crossed | "Replace now: fatigue past threshold, high leverage, unfavorable matchup." |

## Inputs

- `features.fatigue.v1`
- `features.leverage.v1`
- `features.matchup.v1`
- `game_state.raw` for current inning, outs, score differential

## Logic

Rule-based in Phase 1 for explainability. Each alert carries an
`inputs_snapshot_uid` so the reconciliation layer can look up exactly what
the streaming job saw at emit time.

A Phase 3 follow-up replaces the rules with a learned model trained on the
batch-side outcomes, keeping the snapshot mechanism intact.

## Sink

`alerts.v1` topic, consumed by the dashboard and persisted to the Iceberg
bronze layer for reconciliation.
