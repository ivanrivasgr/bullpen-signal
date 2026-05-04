# Commit plan

A suggested sequence for landing Bullpen Signal as a series of real commits
rather than one giant drop. Each item is one coherent commit with a small
behavioral or documentation surface.

Make it your own: renaming, reordering, dropping items, merging items, and
adding items are all fine. Avoid squashing the project into a single commit.

## Milestone 1 - bronze lakehouse

Closed on 2026-05-01.

Delivered:

1. Repository scaffolding, local Docker stack, and CI.
2. Replay engine event models, sources, noise injection, and dry-run runner.
3. Avro schemas and Schema Registry integration.
4. PyFlink smoke job reading Kafka Avro pitch events.
5. Event-time watermarks with bounded out-of-orderness.
6. Parallel smoke execution and keyed count output.
7. Bronze Iceberg table definition as code.
8. Flink StatementSet branch writing decoded pitches to `bronze.pitches`.
9. DuckDB inspection helper over PyIceberg snapshot reads.
10. Integration coverage for Kafka -> Flink -> Iceberg bronze writes.
11. Milestone 1 architecture docs, ADRs, and public summary draft.

## Milestone 2 - silver layer + initial fatigue signal

Target window: 2026-05-04 through 2026-05-08.

Planned commits:

1. Clean milestone vocabulary in project docs.
2. Plan the silver-layer milestone and initial fatigue signal.
3. Record silver design decisions and dbt-on-DuckDB engine choice.
4. Define silver Iceberg schemas as code.
5. Scaffold the dbt-duckdb project.
6. Build `silver.pitch_events` from `bronze.pitches`.
7. Add integration coverage for bronze -> silver pitch events.
8. Build `silver.pitcher_game_fatigue`.
9. Add integration coverage for fatigue buckets.
10. Add end-to-end bronze -> silver -> fatigue coverage.
11. Close the milestone with docs and demo queries.

## Later milestones

Later milestones should stay explicit and bounded:

- Live streaming fatigue, matchup, and decision-support signals.
- Alert orchestration.
- Gold/mart tables for serving and reconciliation.
- Dashboard views backed by real data.
- Stationarity mini-probe for the public governance commitment.
- Cloud deployment and lineage/observability hardening.
