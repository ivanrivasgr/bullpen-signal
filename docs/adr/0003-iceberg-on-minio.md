# ADR 0003 — Iceberg on MinIO for the lakehouse

- **Status:** Accepted
- **Date:** Phase 0

## Context

Need a table format for the medallion layers. The reconciliation story
depends on snapshots, time travel, and rollback being real operations, not
theoretical ones.

## Decision

Apache Iceberg with a REST catalog, backed by MinIO locally and S3 in the
cloud demo. dbt reads via DuckDB's Iceberg extension in Phase 0 and 2;
Phase 4 optionally adds a warehouse target.

## Alternatives considered

- **Delta Lake.** Equivalent for most of what we need. Iceberg wins on
  catalog-standard maturity for the project's specific use of
  snapshot-based reconciliation queries.
- **Hudi.** Stronger CDC story but weaker integration with the Python/dbt
  tooling we already use. The CDC aspect is a small part of the project,
  not worth reshaping the stack around.
- **Plain Parquet + Hive metastore.** No snapshots, no time travel,
  no safe concurrent writes. Kills the reconciliation story.

## Consequences

- The lakehouse is authoritative. Anything that lands in Iceberg has a
  snapshot id that can be cited in a case study.
- Rolling back a bad batch run is a first-class operation, not a restore
  from backup.
- MinIO for local introduces one extra container; the operational load is
  low and the dev parity with cloud is high.
