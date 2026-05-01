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

## Milestone 1 Verified Flow - 2026-05-01

Milestone 1 now has a verified local streaming-to-lakehouse path:

1. Synthetic baseball pitch events are produced by the replay engine.
2. Events are encoded as Avro values with Confluent framing.
3. Redpanda Kafka stores the raw `pitches.raw` stream.
4. Redpanda Schema Registry serves the Avro contracts used by Flink.
5. The PyFlink smoke job reads Kafka through the Table API.
6. Event-time watermarks are derived from `event_time`.
7. Print sinks keep direct runtime observability through `[smoke_job]` and `[smoke_counts]`.
8. A parallel StatementSet branch writes decoded pitches into `bullpen.bronze.pitches`.
9. Iceberg REST catalog tracks table metadata.
10. MinIO stores Iceberg metadata and data files.
11. Local inspection uses PyIceberg snapshot reads registered into DuckDB for SQL.

Confirmed working locally:

- Kafka Avro publish and decode
- Schema Registry contract registration
- Flink event-time source DDL
- Parallel smoke job execution
- Durable Iceberg bronze writes
- Snapshot-aware local bronze inspection
- Integration coverage for Kafka -> Flink -> Iceberg

Designed but not implemented yet:

- Silver table modeling
- Fatigue, leverage, and matchup signal jobs
- Alert orchestrator
- Serving-layer projections
- Dashboard/API consumers
- Production orchestration
