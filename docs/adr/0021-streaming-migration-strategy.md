# ADR 0021 - Streaming Migration Strategy: Making the Dual-Path Comparison Real

- **Status:** Accepted
- **Date:** 2026-06-12

## Context

ADR 0001 committed the project to a dual-path architecture and named the
reconciliation between the two paths as the product: "the reconciliation
dashboard is the product. A regression there is a regression in the thesis."
The streaming path was to emit provisional features in seconds; the batch path
to produce canonical truth with full context; the reconciliation layer to
record the delta between them.

Phase 3 built the reconciliation layer. But it currently reconciles the batch
path against itself. The matchup signal is generated only in dbt
(silver_matchup_signals); there is no streaming implementation, so the
"provisional versus canonical" comparison the thesis depends on does not yet
exist. The should-have-fired ledger and reconciliation summary work, but the
two inputs they compare both come from batch. The delta they measure today is
the delta introduced by the uncertainty window simulation, not the delta
between a real-time decision and the truth that arrived later.

This ADR decides how the streaming path is built so that the comparison becomes
real, and in what order.

## What "real" requires

The reconciliation is only meaningful if the streaming signal is point-in-time
honest. A streaming matchup signal must use only information available at the
replay clock — season-to-date splits as of that moment, the lineup state as
known then (confirmed or projected), no data from later in the game or season.
If the streaming job reaches for season totals or the confirmed lineup before
confirmation actually arrived, it is not deciding in real time; it is peeking,
and the reconciliation measures nothing.

This is the hard constraint that shapes the whole migration. It is also exactly
the constraint Phase 3 already modeled in batch: the uncertainty window, the
projected-versus-observed batter, the reduced-versus-full confidence bands. The
streaming job must reproduce that point-in-time discipline natively, not as a
simulation but as the real consequence of consuming an event stream in order.

## Decision

### Order of migration: signal generation first, reconciliation last

The streaming path is built in this order, and the reasoning is that each step
unblocks the next:

1. **Streaming matchup signal generation** is the first job. It computes the
   matchup signal per pitch, in event-time order, with Flink state, using only
   point-in-time information. This is what is missing today. Until it exists,
   there is nothing new to reconcile.

2. **The batch matchup signal already exists** (silver_matchup_signals) and is
   the canonical side of the comparison. No new work; it is the reference.

3. **The reconciliation layer already exists** (Phase 3). Once the streaming
   signal lands on its own Kafka topic, the existing reconciliation marts gain
   a real provisional input to compare against canonical. The marts may need to
   point at the streaming topic instead of (or alongside) the batch signal
   table, but the taxonomy and the ledger do not change.

Reconciliation is not migrated; it is fed. This is the payoff of having built
Phase 3 first: the streaming work has a target to satisfy, not a contract to
invent.

### The shared contract that makes the comparison valid

The streaming and batch signals must be comparable apples to apples. Both must
emit, for the same pitch:

- the same natural key (game_pk, at_bat_number, pitch_number),
- the same lineup_state_at_emission and confidence_band vocabulary
  (ADR 0016, 0020),
- the same signal definition, so a difference in signal_value reflects a
  difference in information, not a difference in formula.

The signal-generation logic lives in one place today (signals/matchup_signal.py,
a pure function). The streaming job must call the same definition, not a
reimplementation, or the two paths drift and the reconciliation measures the
drift instead of the latency cost. ADR 0001 warned of exactly this: "Every
feature has a streaming implementation and a batch implementation. These can
drift; tests must enforce that the canonical values match the definition."

How a PyFlink job invokes a Python pure function inside the JVM-backed Table API
runtime is an open implementation question (a Python UDF is the likely path).
If it proves infeasible to share the function directly, the fallback is a
contract test that runs the same inputs through both paths and asserts equality,
making any drift a test failure.

### Honest scope: contract first, rich signal later

The matchup job README describes a rich signal — pitch-mix probabilities, xwOBA
by pitch type, park factors, KEEP/WARM/REPLACE recommendations. The batch signal
does not compute any of that yet; signal_value is a placeholder keyed on
handedness (ADR 0016). The streaming job will therefore replicate the current
placeholder contract first, not the rich signal. Building the rich wOBA
computation in streaming while the batch reference is still a placeholder would
produce two things that cannot be reconciled, because the canonical side has
nothing to compare. The rich signal is future work for both paths together,
governed by its own ADR, and only meaningful once both paths compute it from the
same definition.

## What is locked by ADR 0012 and inherited here

ADR 0012 already fixed the streaming foundation, and this ADR does not revisit
it: Avro values with Confluent framing, Redpanda's Schema Registry, the Table
API over PyFlink 1.20 (the DataStream Python Avro path was rejected after a
failed attempt), pinned connector JARs copied into /opt/flink/lib, and
schema-as-code bronze tables. The streaming matchup job is built on this
foundation. The smoke job is the working reference for the catalog DDL, the
Avro source setup, and the Iceberg sink configuration.

## Alternatives considered

### Migrate the reconciliation path to streaming first

Rejected. The reconciliation is inherently retrospective — it compares a
provisional decision to a truth that arrives later. Moving it to streaming
before a streaming signal exists would mean reconciling batch against batch in
a more complicated runtime, with no new information. The reconciliation is the
consumer of the comparison, not the producer; it is built last because it
depends on the streaming signal existing.

### Build the rich wOBA signal directly in streaming

Rejected for now. The batch reference is a placeholder. A rich streaming signal
would have no canonical counterpart to reconcile against, violating the thesis.
Both paths must adopt the rich signal together, under a later ADR.

### Reimplement the signal logic in the Flink job

Rejected as the default. ADR 0001 explicitly warned that streaming and batch
implementations drift. The streaming job should call the shared definition; if
the runtime makes that infeasible, a contract test enforcing path equality is
the required mitigation, not silent reimplementation.

## Consequences

- The next streaming commit is a matchup signal job that consumes pitches.raw,
  computes the signal per pitch in event-time order using point-in-time state,
  and publishes to a new streaming matchup topic whose exact name the
  implementation commit will fix.
- The reconciliation marts gain a real provisional input. This is the first
  time the dual-path delta in ADR 0001 is measurable rather than simulated.
- Point-in-time honesty becomes a tested property, not an aspiration. The job
  must be unable to see the confirmed lineup before confirmation, mirroring the
  uncertainty window Phase 3 built in batch.
- The matchup/leverage/fatigue/alert_orchestrator jobs remain README-only
  scaffolding. This ADR governs the matchup job; the others follow the same
  pattern once it is proven.

## References

- ADR 0001: why dual-path; the reconciliation is the product
- ADR 0012: streaming foundation decisions (Avro, Table API, connector JARs)
- ADR 0016: matchup signal design and placeholder magnitudes
- ADR 0020: dbt double-emission resolution; the batch reconciliation contract
- Phase 3 closeout: `docs/phase3/phase3_closeout.md`
- Matchup job sketch: `streaming/flink_jobs/matchup/README.md`
