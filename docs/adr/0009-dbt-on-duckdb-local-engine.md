# ADR 0009 - dbt On DuckDB As The Local Silver Engine

- **Status:** Accepted
- **Date:** 2026-05-04

## Context

ADR 0001 established a dual-path architecture: streaming for fast provisional
signals, batch for canonical reconstruction. Milestone 1 delivered the bronze
streaming path. Milestone 2 starts the batch/silver path.

The repo does not yet have a dbt project. Adding silver transforms without dbt
would keep the local workflow moving, but it would defer the modeling framework
that the architecture already depends on.

## Decision

Use dbt as the model framework and DuckDB as the local execution engine for
Milestone 2.

The repo will add a `dbt/` project with:

- `dbt_project.yml`
- `profiles.yml.example`
- `models/silver/`
- `models/marts/`
- source definitions for `bronze.pitches`
- model tests and custom SQL tests

`silver.pitch_events` is incremental. `silver.pitcher_game_fatigue` is a table.

## Trade-Offs

DuckDB keeps the local setup small compared with Spark. It is also fast enough
for the synthetic replay and historical-window work planned for the next
milestones.

The cost is that local Iceberg integration is less direct than a production
warehouse. DuckDB is not the system of record for Iceberg table metadata. When
models need to write Iceberg-backed outputs locally, the workflow writes Parquet
data with Iceberg-compatible paths and registers the resulting snapshot through
PyIceberg after the dbt run.

That workaround is deliberate. It keeps dbt responsible for model SQL and keeps
PyIceberg responsible for Iceberg catalog state.

## Alternatives Considered

### Python transforms over DuckDB and PyIceberg

Rejected for Milestone 2. It would work locally, but it would bypass the dbt
modeling layer promised by the architecture.

### Spark for local silver transforms

Rejected for now. Spark would be closer to a large lakehouse deployment, but it
adds operational weight before the first silver contracts exist.

### Warehouse-first implementation

Rejected for local development. The project still needs a reproducible laptop
path before a cloud target is introduced.

## Consequences

- SQL models become the contract for the batch path.
- dbt tests become part of the quality gate.
- Local development stays reproducible without requiring a cloud warehouse.
- The Iceberg registration workaround must stay documented and tested.
