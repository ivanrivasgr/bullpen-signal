# Milestone 2 Closeout — Silver Layer + Fatigue Signal

- **Status:** Closed
- **Closed:** 2026-05-10
- **Started:** 2026-05-04
- **Duration:** 7 days (3-day slip from original target of 2026-05-08)

## What Was Delivered

### Silver design — ADRs

| SHA | Title |
|-----|-------|
| `9fd9e4e` | docs(phase1): plan milestone 2 silver and fatigue |
| `c33fd3d` | docs(adr): silver design decisions and dbt-on-duckdb engine choice |
| `0415ab5` | docs(adr): clarify silver out-of-scope governance inputs |

### Lakehouse schemas as code

| SHA | Title |
|-----|-------|
| `a7453f9` | feat(lakehouse): silver schemas as code |

### dbt-duckdb scaffold + silver_pitch_events model

| SHA | Title |
|-----|-------|
| `b2e7cf9` | feat(dbt): scaffold dbt-duckdb project with iceberg source refresh |
| `2491737` | feat(silver): pitch events transform from bronze via dbt |
| `3f82656` | refactor(dbt): split iceberg I/O from dbt SQL execution after duckdb compat issue |
| `22ad10b` | docs(adr): amend 0009 with iceberg-via-pyiceberg execution context |
| `ab576be` | test(integration): silver pitch events lands data from bronze |

### venv split — resolve PyFlink/PyIceberg conflict

| SHA | Title |
|-----|-------|
| `165b3db` | feat(deps): split venv-batch for pyiceberg writes |

### silver_pitcher_game_fatigue model

| SHA | Title |
|-----|-------|
| `ed99230` | feat(silver): pitcher game fatigue model with workload threshold buckets |

### silver → Iceberg publish

| SHA | Title |
|-----|-------|
| `4a36118` | feat(lakehouse): publish silver outputs from duckdb to iceberg |

### End-to-end integration test + closeout

| SHA | Title |
|-----|-------|
| `6071fb0` | test(integration): bronze to silver to fatigue end-to-end |
| `(this commit)` | docs: milestone 2 closeout |

## Metrics

| Metric | Value |
|--------|-------|
| Unit tests | 94 (across 15 test files) |
| Integration tests added this milestone | 3 (`test_silver_pitch_events`, `test_silver_pitcher_game_fatigue`, `test_bronze_to_silver_to_fatigue_e2e`) |
| Integration tests total | 7 |
| ADRs created | ADR 0008 (silver design) |
| ADRs amended | ADR 0009 (dbt-on-duckdb engine) — 3 amends: 2026-05-06 iceberg-via-pyiceberg, 2026-05-10 venv split, 2026-05-10 silver publish path |
| Iceberg tables operational | `bronze.pitches`, `silver.pitch_events`, `silver.pitcher_game_fatigue` |
| dbt models | 2 (`silver_pitch_events` incremental, `silver_pitcher_game_fatigue` table) |
| dbt tests | 31 (schema contract tests across both models) |

## Architectural Decisions

**Split venvs (`.venv` streaming, `.venv-batch` batch+publish).**
Resolves the `apache-beam 2.61` (`pyarrow<17`) vs `PyIceberg 0.11.1` write path
(`pyarrow>=17`) conflict. Downgrade of either dependency was rejected as fragile.
`dbt/run.sh` activates `.venv-batch` automatically. See ADR 0009 amend 2026-05-10.

**PyIceberg materialize-then-dbt instead of `iceberg_scan()`.**
The DuckDB Iceberg extension aborts with a `DATE → INTEGER` cast failure when
reading the bronze manifest Avro file. Workaround: `materialize_dbt_sources.py`
reads the Iceberg snapshot via PyIceberg and writes it as a native DuckDB table
before each dbt run. dbt SQL is unchanged; the workaround is in the wrapper.
See ADR 0009 amend 2026-05-06.

**Snowplow telemetry disabled via env var.**
`dbt-core 1.11` flushes anonymous usage events through a Snowplow C extension at
process exit. On WSL2 kernel 6.6.87.1-microsoft-standard the flush crashes with
`SIGABRT`. Fixed by `DBT_SEND_ANONYMOUS_USAGE_STATS=False` in `dbt/run.sh`.
See ADR 0009 amend 2026-05-06.

**`fatigue_bucket` thresholds: low <25, medium 25–49, high ≥50.**
Deliberately arbitrary placeholders. Threshold validity is not assumed.
Validation deferred to the stationarity mini-probe (external commitment to
Chad Corwin, scheduled week 2026-05-18 through 2026-05-22, tracked in
`docs/external_commitments.md`).

**`publish_dbt_silver.py` appends by default; `--full-refresh` overwrites.**
Append is consistent with the incremental dbt run pattern. `--full-refresh`
uses `AlwaysTrue` overwrite filter for development and CI resets.
Schema verification (column coverage + Arrow type cast) runs before every write.

## What Was NOT Delivered (Out of Scope)

| Item | Target |
|------|--------|
| Gold layer aggregate marts | Milestone 3 |
| Dashboard / visualization | Milestone 3+ |
| Alert orchestrator (real-time fatigue alerts) | Milestone 4 |
| Streaming fatigue updates (live recomputation per pitch) | Milestone 4 |
| CI integration job (Docker-based) | Known debt; integration tests run locally only |
| Stationarity mini-probe (public commitment to Chad Corwin) | Scheduled 2026-05-18–2026-05-22 |

## Known Technical Debt

**CI does not run integration tests.**
The `tests/integration/` directory exists and all tests pass locally with
`pytest -m integration` when the Docker stack is up. No CI job runs
`docker compose up` before the test suite. This is the most consequential
open gap — a regression in the bronze-to-silver pipeline would not be caught
automatically until someone runs the tests manually.

**Silver → Iceberg publish accumulates snapshots indefinitely.**
`publish_dbt_silver.py` appends by default. Snapshot compaction and retention
policy are out of scope for Milestone 2.

**Two venvs require operational discipline.**
Use `.venv` for streaming/Flink work; use `.venv-batch` (or `./dbt/run.sh`)
for batch+publish work. No tooling enforces this separation; it relies on
developer awareness and the error message in `dbt/run.sh`.

**`_build_synthetic_pitches(n)` helper supports n ≤ 6 cleanly.**
The helper uses `second=i*10`, which overflows at `n=7` (second=60 is
invalid). Integration tests that need larger counts use pool replication
(`pool[i % len(pool)]`). This is a known rough edge in the test helpers,
not a production code issue. Not a refactor target for this milestone.

## Lessons Learned

**DuckDB Iceberg extension is not production-ready for all Avro manifest
formats.** The `DATE → INTEGER` cast failure in `iceberg_scan()` is
silent about its root cause and presents as a generic abort. Debugging
required isolating the Iceberg path from the Snowplow path (two separate
crash modes with the same observable symptom).

**dbt-core 1.11 Snowplow telemetry is incompatible with WSL2 kernel 6.6.87+.**
Both crashes (Iceberg cast + Snowplow flush) presented as WSL2 shell drops.
Separating the two failure modes required reproducing each independently.
The env var fix is one line; finding it cost two WSL host restarts.

**PyIceberg 0.11 write path couples to pyarrow 17; PyFlink 2.2.0 couples to
pyarrow <17 via apache-beam 2.61.** Coinstalling both is not possible.
The split-venv approach is the durable resolution. Downgrade was rejected
because PyIceberg 0.10.x has known correctness issues with the REST catalog.

**`duckdb.connect().execute().arrow()` changed return type in DuckDB 1.5.**
It now returns a `RecordBatchReader`, not a `pa.Table`. The correct call
is `.to_arrow_table()`. Type errors from this surface at call sites that
use `pa.Table` methods (e.g., `.column()`), not at the execute call itself.

**PyIceberg requires precise schema nullability when appending.**
Passing an Arrow table whose fields are all nullable (DuckDB default) to
`table.append()` fails when the Iceberg schema marks fields as `required`.
The fix: `pa.table(data, schema=expected_schema)` applies the Iceberg
schema's nullability to the resulting Arrow table before the write.

## Next: Milestone 3 Anchor (Placeholder)

No firm commitment exists for Milestone 3 scope or start date. The following
decisions must be addressed when Milestone 3 begins:

- Define gold layer marts for fatigue, leverage, and matchup composite signals.
- Decide whether the CI integration job (docker-compose) is unblocked before
  or alongside gold layer work.
- Address dataset scaling beyond synthetic replay fixtures (historical Statcast
  pull scope and cadence).

Plan document to be created at `docs/milestones/milestone_3_signal_layer_plan.md`
when Milestone 3 begins.
