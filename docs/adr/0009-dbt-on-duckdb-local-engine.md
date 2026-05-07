# ADR 0009 - dbt On DuckDB As The Local Silver Engine

- **Status:** Accepted, amended 2026-05-06
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

## Update 2026-05-06

Two compatibility issues appeared during Day 3 implementation. Both required
changes to the local execution context. The dbt model SQL is unchanged.

**DuckDB iceberg_scan and the DATE→INTEGER cast failure.** When `dbt run`
attempted to read `bronze.pitches` via `iceberg_scan()`, DuckDB's Iceberg
extension aborted with "Unimplemented type for cast (DATE → INTEGER)" while
parsing the manifest Avro file on MinIO. The root cause is a type-coercion
gap in the DuckDB Iceberg extension for this manifest format — not a bronze
schema error, not a MinIO configuration error.

The fix: add a materialization step before each `dbt run`.
`infra/scripts/materialize_dbt_sources.py` reads the current `bronze.pitches`
Iceberg snapshot via PyIceberg and writes it into the local DuckDB database as
a native table using Arrow. dbt then reads from that DuckDB table as its
source. The dbt source definition and all model SQL are unchanged.

This shifts an assumption from the original ADR. The original assumed
dbt-duckdb would handle Iceberg I/O on both sides via `iceberg_scan()` and
the DuckDB Iceberg extension's write path. In practice, the read path needs
PyIceberg materialization (this amend) and the write path will likely also
need PyIceberg (separate amend before Milestone 2 closeout). The split is
now: dbt owns model SQL only; PyIceberg owns Iceberg snapshot I/O on both
read and write.

**Snowplow telemetry SIGABRT on WSL2.** dbt-core 1.11.8 flushes anonymous
usage events at end of run via a Snowplow C extension. On WSL2 kernel
6.6.87.1-microsoft-standard, that flush crashes on connection teardown with
SIGABRT, killing the process before any dbt result lands.

Both crashes presented the same observable symptom (process abort, WSL2 shell
drops). During investigation, two WSL host crashes occurred before the failure
modes were separated. The Iceberg cast issue was reproducible from
`iceberg_scan()`. The Snowplow flush issue was reproducible from `dbt parse`
alone, with no Iceberg involved. The fix sequence reflects that separation:
PyIceberg materialization removed the first failure path, telemetry disable
removed the second.

The fix: set `DBT_SEND_ANONYMOUS_USAGE_STATS=False` in `dbt/run.sh`. It is
not a recommendation for team usage where upstream usage reporting has value
and where the WSL2 kernel issue does not apply.

**Trade-off: the materialization step is local-only scaffolding.** Cloud
execution paths — Snowflake, Athena, Redshift Spectrum — read Iceberg natively
and do not need a DuckDB materialization step before a dbt run. The same dbt
SQL models run unchanged against those engines. Local disk doubles (Iceberg
Parquet files plus the DuckDB native table), which is acceptable at dev and
integration-test data volumes.

**Still open before Milestone 2 closeout.** The write path — reading
`silver.pitch_events` from DuckDB and publishing it to Iceberg as
`silver.pitch_events` via PyIceberg — is not yet implemented. That decision
involves schema-as-code alignment (`lakehouse/schemas/silver_pitch_events.py`
already exists), partition spec, and CREATE TABLE vs append behavior. A
separate ADR amend will document it before Milestone 2 closes.
