# Bullpen Signal dbt Project

This project contains the local batch modeling path for Bullpen Signal.

Milestone 2 uses dbt with DuckDB as the local execution engine. The initial
target path is:

- `bronze.pitches`
- `silver.pitch_events`
- `silver.pitcher_game_fatigue`

## Setup

Copy the example profile before running dbt:

    cp dbt/profiles.yml.example dbt/profiles.yml

The local stack must be running, and `bronze.pitches` must already contain data
from the streaming smoke job.

## Running dbt

Use the wrapper from the repo root:

    ./dbt/run.sh --select silver_pitch_events

The wrapper first runs:

    python infra/scripts/refresh_iceberg_sources.py

That script asks the local Iceberg REST catalog for the current
`metadata-location` of `bronze.pitches` and writes it to
`dbt/.iceberg_sources.json`. The wrapper then passes the resolved location to
dbt as `bronze_pitches_location`.

This vars-plus-wrapper approach is intentionally simpler than a custom Jinja
macro that reads files at compile time. It centralizes the operational
dependency that bronze source metadata must be refreshed before dbt runs.

## Direct dbt Commands

From the `dbt/` directory:

    dbt deps
    dbt parse --profiles-dir .

For `dbt run`, prefer `./dbt/run.sh` from the repo root so source metadata is
fresh.

## Notes

Do not commit `profiles.yml`, `.iceberg_sources.json`, `target/`,
`dbt_packages/`, or local DuckDB database files. Those are intentionally ignored
by `dbt/.gitignore`.

dbt-duckdb does not resolve the Iceberg REST catalog directly. The local
workflow refreshes the active Iceberg metadata path before running dbt instead
of using a static external location.
