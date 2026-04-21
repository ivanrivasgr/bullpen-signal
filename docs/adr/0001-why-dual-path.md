# ADR 0001 — Why a dual-path architecture

- **Status:** Accepted
- **Date:** Phase 0

## Context

Live in-game decisions in baseball (pull the pitcher, warm the bullpen,
change for matchup) need sub-second feedback. Canonical metrics (season
splits, win probability, fatigue curves) need completeness and correctness.
A single pipeline that tries to satisfy both ends up doing neither well:
push it toward low latency and you sacrifice corrections and backfills;
push it toward correctness and you miss the operational window.

The project's thesis is that these are two distinct problems with two
distinct right answers, and that the interesting artifact is not either path
in isolation but the reconciliation between them.

## Decision

Run two paths over the same replay stream:

1. **Streaming** — Flink jobs with event time, stateful aggregations, and
   exactly-once delivery. Emits provisional features and alerts in seconds.
2. **Batch** — dbt incremental models over Iceberg that apply late arrivals,
   corrections, and full-season context to produce canonical truth.

A dedicated reconciliation schema compares every streaming alert to the
canonical truth and records the delta.

## Alternatives considered

- **Streaming-only with a corrections topic.** Kappa-style. Technically
  clean but the "canonical truth" is implicit in the last state of the
  stream, which hides the exact thing we want to expose — the delta between
  provisional and final.
- **Batch-only with micro-batches.** Cheaper to operate, but the whole point
  is to surface what real-time gets you first. Micro-batches collapse that
  dimension.
- **Two independent pipelines with no reconciliation.** Produces two
  dashboards nobody trusts. The reconciliation layer is load-bearing.

## Consequences

- More moving parts. Flink, dbt, Iceberg, and a reconciliation schema all
  need to stay healthy.
- Every feature has a streaming implementation and a batch implementation.
  These can drift; tests must enforce that the canonical values match the
  definition documented in each feature's spec.
- The reconciliation dashboard is the product. A regression there is a
  regression in the thesis.
