# ADR 0004 — PyFlink over Java Flink for Phase 1

- **Status:** Accepted, with a revisit at Phase 4
- **Date:** Phase 0

## Context

The streaming jobs need to be written in something. Flink natively supports
Java and Python; dialects differ in maturity and performance.

## Decision

PyFlink for Phase 1. Same language as the replay engine, the dashboard, and
the dbt macros (for the ones that drop into Python). Keeps the project
navigable for one person and reduces the switch cost of a change that
touches streaming and batch in the same PR.

Revisit at Phase 4: if a specific job is pinned on PyFlink overhead (UDF
serialization, Python GIL around stateful ops), port that one job to Java.

## Alternatives considered

- **Java DataStream API.** Best performance, best operator library, worst
  iteration speed for a solo developer.
- **Flink SQL only.** Works for the leverage job (mostly SQL-shaped), falls
  short for the fatigue job (rolling windows with custom weighting).
- **Kafka Streams.** No event-time watermarks story as mature as Flink's,
  and a weaker ecosystem of connectors for Iceberg.

## Consequences

- Adopting Java later is acceptable and expected for any job that proves to
  be a bottleneck. The build is set up so that one Maven module per Java
  job can coexist alongside the PyFlink jobs.
- PyFlink requires Python 3.11 on the TaskManagers; the Flink images used
  in `infra/docker/docker-compose.yml` include a compatible runtime.
