# Reconciliation

Where the streaming alerts meet the canonical truth. Every alert emitted by
the Flink `alert_orchestrator` is joined against the corresponding
batch-canonical value, and the delta is recorded.

This is the schema that feeds the dashboard's reconciliation view and the
benchmark tables in the Medium article.

## Planned models (Phase 3)

| Model | Grain | What it records |
|---|---|---|
| `fct_alert_reconciliation` | One row per streaming alert | Alert at emit time, canonical value at reconciliation time, delta, outcome classification. |
| `fct_signal_delta_timeseries` | Pitcher-signal-pitch | Streaming vs batch feature value at each pitch, for distribution plots. |
| `fct_decision_outcomes` | Alert-action | Did the alert fire before the batch would have? Would batch have agreed? |

## Outcome classifications

Each alert falls into one of:

- `confirmed` — batch agrees with the streaming alert.
- `confirmed_late` — batch would have fired the same alert, just later.
- `reversed` — batch recomputes and the alert was wrong.
- `softened` — batch would have fired a lower-severity alert.
- `escalated` — batch would have fired a higher-severity alert; streaming undersold the moment.

The distribution of these across many games is the empirical core of the project.

## Why this is its own schema

Reconciliation spans streaming and batch. Putting it inside `marts` buries
the lede. A dedicated schema makes the dashboard query clean and makes the
case-study queries live next to their source of truth.
