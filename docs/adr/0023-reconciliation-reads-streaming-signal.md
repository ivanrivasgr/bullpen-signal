# ADR 0023 - The Reconciliation Reads the Streaming Signal

- **Status:** Accepted
- **Date:** 2026-06-22

## Context

ADR 0001 named the reconciliation between the streaming and batch paths as
the product: the delta between a real-time decision and the canonical truth
that arrived later. ADR 0021 set the migration order to make that real, and
the streaming matchup job (now built and verified end to end) writes signals
to the streaming.matchup_signals Iceberg table.

But the reconciliation does not read it yet. mart_should_have_fired_ledger —
the ledger Chad named load-bearing for the Phase 3 governance review — reads
its reduced and suppressed signals from silver_matchup_signals, the batch
table. So the ledger today evaluates a batch simulation of the real-time
decision against the realized outcome, not the real-time decision itself. The
"would have been correct" question is asked of the wrong actor: the batch
model pretending to be the streaming path, rather than the streaming path.

This ADR decides that the ledger reads the streaming signal.

## Decision

mart_should_have_fired_ledger reads its reduced and suppressed signals from
the streaming.matchup_signals table, not from silver_matchup_signals.

The reduced and suppressed bands are exactly the decisions the system made
under uncertainty — the ones the ledger evaluates retrospectively against the
outcome. Those decisions belong to the streaming path: it is the path that
emits in real time, during the uncertainty window, before the lineup
confirmed. The batch model reproduces the same emission for validation, but it
is a reproduction. Evaluating the reproduction told us the emission logic was
sound; evaluating the streaming signal tells us the real-time system was
sound. The second is the question the product exists to answer.

The batch table is unchanged. silver_matchup_signals keeps producing its
signals, including the reduced and suppressed ones, and keeps feeding any
validation that compares the two paths' emission logic. This ADR moves only
the ledger's source, not the batch model's existence.

## Why the numbers do not move today, and why the change still matters

The streaming and batch paths share the same core — compute_signal_fields,
derive_handedness_matchup, plan_signal_emissions — by construction (ADR 0021).
On the same pitches they produce identical signal values, bands, and emission
states. So switching the ledger's source from batch to streaming does not, on
today's data, change a single correction rate. The reconciliation summary will
read the same.

That identity is the point, not a reason the change is cosmetic. It is the
evidence that the streaming path reproduces the batch contract exactly — the
anti-drift guarantee the shared core was built for. The change matters because
it makes the ledger evaluate the actor that actually decides in real time. If
the streaming path ever drifts from the batch — a bug, a runtime difference, a
point-in-time leak — the ledger would now catch it, because it reads the
streaming signal. Reading the batch signal could never catch a streaming
regression, because it never looks at the streaming signal. The change closes
that blind spot.

## Implementation plan

The streaming table is Iceberg in MinIO; dbt-duckdb reads Iceberg sources
through a local-dev bridge (materialize_dbt_sources.py) that today is wired for
a single table, bronze.pitches. The work:

1. Generalize the Iceberg-to-DuckDB bridge from a hardcoded
   materialize_bronze_pitches to a function that materializes any
   (namespace, table) the project declares as a source.
2. Add streaming.matchup_signals to refresh_iceberg_sources.py and to run.sh
   so its metadata location is resolved and materialized before dbt runs.
3. Declare the streaming source in sources.yml.
4. Point mart_should_have_fired_ledger at the streaming source.
5. Verify the reconciliation summary produces the same correction rates as
   before the switch, on the same replayed data — proof the wiring is correct
   and the streaming signal matches the batch, now evaluated as the real-time
   decision.

## Consequences

The reconciliation becomes what ADR 0001 described: the streaming path's
real-time decisions, evaluated against the truth that arrived later. The
dashboard stops comparing batch against itself.

The dependency on the streaming job's output is now load-bearing for the
ledger. If the streaming job has not run, the streaming table is empty and the
ledger is empty — the same way the ledger was empty before BATTER_UNCERTAIN
replays populated the batch table. The reconciliation requires the streaming
path to have run, which is correct: there is nothing to reconcile until the
real-time path has decided.

This is the last structural step of the streaming migration. After it, the two
paths exist, the streaming signal is the one evaluated, and what remains is
calibration (deferred to full-season volume) and operational hardening, not
architecture.
