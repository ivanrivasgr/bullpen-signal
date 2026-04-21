# ADR 0005 — DuckDB as the Phase 0 dbt target

- **Status:** Accepted
- **Date:** Phase 0

## Context

Early phases need a dbt target that iterates fast, costs nothing, and plays
cleanly with Parquet. A managed warehouse (Snowflake, BigQuery) is
overkill and slows the loop.

## Decision

DuckDB as the Phase 0 and Phase 2 target. Iceberg-aware reads land in
Phase 2 via DuckDB's Iceberg extension. A managed warehouse is an optional
Phase 4 add.

## Alternatives considered

- **Snowflake.** Great product, unnecessary cost and setup for a solo
  project at this stage.
- **BigQuery.** Same note.
- **Postgres.** Slower on analytic queries; worse Parquet/Iceberg story.

## Consequences

- The models stay portable: ANSI SQL with a small number of DuckDB
  conveniences that are easy to refactor out if a target swap ever
  happens.
- Tests run in seconds, which keeps TDD on the batch side honest.
