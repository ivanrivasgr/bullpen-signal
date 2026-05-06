# Bullpen Signal dbt Project

This project holds the local batch transforms for Milestone 2.

The local engine is `dbt-duckdb`. The source of truth for Iceberg metadata
remains the local Iceberg REST catalog. DuckDB reads the current bronze Iceberg
snapshot through `iceberg_scan(...)`, using a metadata location resolved before
the dbt run.

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
2. passes the active `bronze.pitches` metadata location to dbt through vars
3. publishes selected dbt silver outputs into the matching local Iceberg tables

This keeps dbt responsible for model SQL and keeps PyIceberg responsible for
Iceberg catalog state.

## Requirements

The local Docker stack must be running, and `bronze.pitches` must exist.
For data-bearing runs, `bronze.pitches` must already contain rows.
