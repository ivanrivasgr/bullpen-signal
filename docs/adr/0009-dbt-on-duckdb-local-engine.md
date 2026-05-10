# ADR 0009 - dbt On DuckDB As The Local Silver Engine

- **Status:** Accepted, amended 2026-05-06, amended 2026-05-10
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

## Update 2026-05-10 — Venv Split

**Symptom.** PyIceberg 0.11.1 write path requires pyarrow>=17. The existing
`.venv` pins pyarrow<17 because apache-beam 2.61 (used by the Flink streaming
path) declares `pyarrow<17` as an upper bound. Installing pyarrow>=17 into
`.venv` breaks apache-beam imports.

**Decision.** Split virtual environments rather than downgrade either
dependency. The existing `.venv` becomes the streaming venv (PyFlink +
apache-beam + pyarrow<17). A new `.venv-batch` carries the batch pipeline
dependencies: dbt-core, dbt-duckdb, duckdb, pyiceberg[s3fs,pyiceberg-core],
and pyarrow>=17.

`dbt/run.sh` activates `.venv-batch` at startup and aborts with an actionable
error message if the venv is absent (`make venv-batch`). Integration tests that
write directly to DuckDB (without PyIceberg writes) continue to run from
`.venv` and do not require `.venv-batch`.

**Alternatives considered.**

- Downgrade PyIceberg to a version compatible with pyarrow<17: rejected. PyIceberg
  0.10.x write path has known correctness issues with the REST catalog; the
  team already validated 0.11.1 against the local MinIO stack.
- Downgrade apache-beam to relax the pyarrow upper bound: rejected. The
  streaming Milestone 1 code is frozen; touching its deps risks regression in
  a tested path.
- Docker-isolate the batch run: deferred. Adds operational overhead before the
  project has a CI environment. Revisit when a cloud target is introduced.

**Trade-offs.**

- Operational cost: two active venvs mean two `pip install` surfaces to keep
  up to date. Medium cost, acceptable at this team size and project stage.
- Developer experience: `make venv-batch` is the single setup step. `dbt/run.sh`
  provides a clear error if it is skipped.
- Scope discipline: `.venv` (Milestone 1 streaming code) is never modified by
  this change. Streaming tests remain green on the original venv.

**Verification.**

1. `make venv-batch` completes without error.
2. `.venv-batch/bin/python -c "import pyiceberg, pyarrow; print(pyiceberg.__version__, pyarrow.__version__)"` prints `0.11.x  17.x`.
3. `.venv-batch/bin/python -c "import pyiceberg_core; print('ok')"` prints `ok`.
4. `./dbt/run.sh --select silver_pitch_events` runs end-to-end using `.venv-batch`.
5. `source .venv/bin/activate && pytest tests/unit/ --no-cov -q` stays green.
