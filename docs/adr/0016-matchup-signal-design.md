# ADR 0016 - Matchup Signal Design

- **Status:** Accepted
- **Date:** 2026-05-29

## Context

Phase 2 Milestone 2 generates the first real matchup signal in Bullpen Signal: a value per (pitch, pitcher, batter) that captures who is pitching, who is batting, and how that matchup affects the live signal. Two design decisions are load-bearing before any signal code lands, and both follow constraints already established by earlier ADRs.

The matchup signal must respect the BATTER_UNCERTAIN state introduced in ADR 0013. When `lineup_state = uncertain` or `projected`, the signal cannot be emitted with the same confidence as when `lineup_state = confirmed`. The reconciliation work named in Chad Corwin's 2026-05-19 response and scheduled for Phase 3 depends on the signal carrying enough confidence metadata that a suppressed-decision counterfactual can be reconstructed.

Two decisions are load-bearing for this ADR:

1. **Where the signal is computed.** Batch in dbt over the silver layer, or streaming in a Flink job that consumes pitch events directly from Kafka.
2. **How confidence is encoded.** A categorical enum reflecting lineup_state, or a numeric probability calibrated from signal evidence.

## Decision

### Compute location: batch in dbt for Milestone 2, streaming in Flink for Phase 3

The matchup signal is computed as a dbt model in the silver layer for this milestone. A new model `silver_matchup_signals` materializes from `silver_matchup_events`, which in turn derives from `silver_pitch_events`. This puts the signal logic next to the existing fatigue signal and reuses the same dbt + DuckDB + Iceberg toolchain.

The signal will be migrated to a Flink streaming job in Phase 3 (target: 2026-06-20). That migration is explicit, scheduled, and load-bearing for the project's end-state: the production system needs a live signal, not a batch refresh. The reason this migration is deferred rather than done now is sequencing — defining the signal logic correctly in a testable batch form first means the streaming version is a port, not a design. Phase 3 inherits a defined contract; it does not redesign one.

### Confidence encoding: categorical enum mapped from lineup_state

The signal carries a `confidence_band` column with values `{full, reduced, suppressed}`. The mapping is direct:

- `lineup_state = confirmed` → `confidence_band = full`. The matchup is between known players; the signal is emitted with full weight.
- `lineup_state = uncertain` → `confidence_band = reduced`. The batter identity is approximate (projected via ADR 0015 hierarchy); the signal is emitted but flagged for downstream consumers to weight differently.
- `lineup_state = projected` → `confidence_band = suppressed`. The system is operating on pre-game projections only; the signal is recorded for Phase 3 reconciliation but should not drive live decisions.

The enum encoding is intentional. A numeric confidence value (e.g., `confidence ∈ [0, 1]`) is theoretically more expressive but requires calibration from labeled outcomes that the project does not yet have. Emitting numeric confidence without calibration would look rigorous while resting on arbitrary numbers — the same anti-pattern rejected in ADR 0013 when the probabilistic representation was set aside in favor of the categorical lineup_state column. Consistency matters: the system either trusts categorical state representations end-to-end or it commits to calibration work that this milestone does not include.

If a calibrated source of confidence becomes available in a later milestone (from Phase 3 reconciliation outcomes, or from a downstream model that learns confidence from realized outcomes), this ADR can be extended to add a numeric column alongside `confidence_band`. The categorical encoding remains the durable contract; the numeric column would be additive.

## Alternatives Considered

### Streaming in Flink for Milestone 2

Compute the matchup signal directly in a Flink job that consumes the `pitches.raw` topic, joins against a Kafka-table of recent batter performance, and emits to a `matchup_signals.raw` topic.

Rejected for this milestone, accepted for Phase 3. Two reasons. First, designing the signal logic correctly is a different problem from operating it at streaming latency. Doing both at once means the design churn happens in Flink code, which is harder to iterate on than dbt SQL. Second, the Flink job needs side inputs (handedness lookups, recent batter performance windows, fatigue context) that are not currently exposed as Kafka tables. Building those side inputs is real work and belongs in the streaming phase, not the design phase.

The migration to Flink is scheduled for 2026-06-20 in the project plan. The streaming job will replace the batch model as the source of live signals; the batch model remains as the offline reproducible computation for Phase 3 reconciliation.

### Numeric confidence calibrated from signal evidence

Compute `confidence ∈ [0, 1]` as a function of lineup_state, signal_value magnitude, freshness of the matchup_events row, and historical reliability of the underlying projections.

Rejected. Numeric confidence without a calibration source is arbitrary precision. The factors above are reasonable inputs to a calibration model, but the model itself requires labeled outcomes — which is exactly what Phase 3 reconciliation produces. Adding numeric confidence to the contract today commits the project to a number that downstream consumers will treat as meaningful before it actually is. The categorical encoding avoids that trap and keeps the door open: once Phase 3 reconciliation produces correction rates by lineup_state, a follow-up ADR can introduce calibrated numeric confidence as an additive column.

### Hybrid: dbt for the join, Python UDF for the signal value

Materialize the matchup features in dbt but compute the signal value in a Python module called as a dbt model post-hook or as a separate orchestration step.

Rejected. The split increases the surface area without changing the semantics. Either dbt owns the signal end to end (this ADR's choice) or Flink does (Phase 3). A hybrid creates a third location for signal logic to live, with no benefit over either pure option.

## Out Of Scope For This ADR

- The exact algorithm computing `signal_value`. This ADR establishes where the signal is computed and how its confidence is encoded; the formula itself is detailed in `docs/phase2/milestone_2_plan.md` and refined in implementation. A future ADR may be warranted if the formula turns out to be a load-bearing decision rather than a tuning detail.
- The schema of `silver_matchup_events` (the upstream feature table). That is implementation detail of Milestone 2 and is documented in the milestone plan.
- Threshold values for what `signal_value` magnitudes trigger alerts. That is alert orchestration, scheduled for 2026-06-20.
- The decision to use enum vs string at the storage layer for `confidence_band`. The dbt model stores it as a string with a check constraint via dbt tests; the Avro contract for the signal event uses a `string` field with a documented allowed-values set. This matches the pattern established for `lineup_state` in ADR 0013.

## Consequences

- A new dbt model `silver_matchup_signals` materializes from `silver_matchup_events`. The model is incremental on the natural key of pitch events, consistent with `silver_pitch_events`.
- The `confidence_band` column is added to the matchup signal contract with allowed values `{full, reduced, suppressed}`. dbt tests enforce the allowed-values constraint at build time.
- Downstream consumers that don't yet care about confidence can filter `confidence_band = 'full'` to get the high-confidence subset. Consumers that participate in Phase 3 reconciliation read all bands and weight accordingly.
- The Phase 3 reconciliation work has a clean target: the `should_have_fired_ledger` mart filters on `confidence_band IN ('reduced', 'suppressed')` to identify decisions the system did not commit to with full weight, then evaluates them against canonical outcomes.
- The Flink migration scheduled for 2026-06-20 inherits a defined signal contract: same input schema, same output schema, same confidence semantics. Only the execution model changes.
- Adding numeric confidence in a future milestone is mechanically simple: extend the contract with a `confidence_numeric` column, keep `confidence_band` as the categorical durable signal. No breaking change.

## References

- ADR 0013: BATTER_UNCERTAIN state representation — `docs/adr/0013-batter-uncertain-state-representation.md`
- ADR 0014: Uncertainty window injection mechanism — `docs/adr/0014-uncertainty-window-injection-mechanism.md`
- ADR 0015: Projected batter source during uncertainty — `docs/adr/0015-projected-batter-source-during-uncertainty.md`
- Phase 2 Milestone 2 plan — `docs/phase2/milestone_2_plan.md`
- Counterparty response sharpening the Phase 3 reconciliation constraint — `docs/mini_probe/2026_05_19_chad_response.md`
