# Bullpen Signal dbt Project

This project holds the local batch transforms for Milestone 2.

The local engine is `dbt-duckdb`. The source of truth for Iceberg metadata
remains the local Iceberg REST catalog.

DuckDB's native `iceberg_scan(...)` is not used for bronze in the local
workflow because it currently fails on the local Iceberg manifest path with a
DATE -> INTEGER conversion error. Instead, the wrapper reads the current
Iceberg snapshot through PyIceberg, materializes that snapshot into the local
DuckDB database, and runs dbt SQL over the resulting `bronze.pitches`
relation.

dbt owns model SQL. PyIceberg owns Iceberg snapshot reads.

## Local Run

Create the ignored local profile once:

```bash
cp dbt/profiles.yml.example dbt/profiles.yml
```

Run models through the wrapper:

```bash
./dbt/run.sh --select silver_pitch_events
```

The wrapper does three things:

1. refreshes `dbt/.iceberg_sources.json` from Iceberg REST
2. materializes the active `bronze.pitches` snapshot into DuckDB
3. runs the selected dbt models

Silver outputs currently land in the local DuckDB database
(`~/.bullpen/dbt.duckdb`) only. Publishing silver back to Iceberg via
PyIceberg will be added in a follow-up commit before Milestone 2 closeout.
Until then, querying silver from outside dbt requires connecting to the same
DuckDB file.

## Requirements

The local Docker stack must be running, and `bronze.pitches` must exist.
For data-bearing runs, `bronze.pitches` must already contain rows.
