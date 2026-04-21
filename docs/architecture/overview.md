# Architecture

High-level view. For decision rationale see `docs/adr/`.

## The shape of the system

```
                Statcast + StatsAPI
                       │
                       ▼
               ┌───────────────┐
               │ Replay engine │   deterministic, speed-configurable
               └───────┬───────┘
                       │  pitches.raw, game_state.raw, corrections.cdc
                       ▼
                 ┌──────────┐
                 │ Redpanda │
                 └────┬─────┘
          ┌──────────┴──────────┐
          │                     │
          ▼                     ▼
  ┌────────────────┐    ┌───────────────┐
  │ Flink jobs     │    │ dbt (batch)   │
  │ fatigue /      │    │ stg → int →   │
  │ leverage /     │    │ marts / recon │
  │ matchup /      │    │               │
  │ alert orch.    │    │               │
  └──────┬─────────┘    └───────┬───────┘
         │                      │
         ▼                      ▼
      alerts.v1         ┌──────────────┐
         │              │ Iceberg      │
         │              │ bronze /     │
         │              │ silver /     │
         │              │ gold         │
         │              └──────┬───────┘
         │                     │
         └──────┬──────────────┘
                ▼
        ┌──────────────────┐
        │ Reconciliation   │
        └────────┬─────────┘
                 │
                 ▼
        ┌──────────────────┐
        │ Streamlit        │
        │ live / canon /   │
        │ reconciliation   │
        └──────────────────┘
```

## Contracts between components

| Producer | Consumer | Contract |
|---|---|---|
| Replay engine | Redpanda | Avro events on `pitches.raw`, `game_state.raw`, `corrections.cdc` |
| Flink jobs | Redpanda, Iceberg | Features on `features.*.v1`, alerts on `alerts.v1`, feature snapshots to Iceberg bronze |
| Iceberg | dbt | Tables exposed via the REST catalog, snapshot-id pinnable |
| dbt reconciliation | Streamlit | `fct_alert_reconciliation` and `fct_signal_delta_timeseries` |
| Streamlit | User | Three views: live, canonical, reconciliation |

## What moves data where

Streaming path uses Flink's Kafka + Iceberg connectors, exactly-once.
Batch path is dbt incremental over DuckDB in Phase 0-2, with the option of
moving to a warehouse target in Phase 4.

## Where the interesting behavior lives

Not in any single job. It lives in the **reconciliation schema**. Every
interesting claim in the Medium article is backed by a query against
`reconciliation.*`. If the reconciliation tables lie, the project lies.
Everything else is plumbing around that claim.
