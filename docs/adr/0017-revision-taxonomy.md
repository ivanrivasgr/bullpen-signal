# ADR 0017 - Revision Taxonomy for Matchup Signal Updates

- **Status:** Accepted
- **Date:** 2026-06-04

## Context

Phase 2 Milestone 2 lands the matchup signal: a per-pitch emission with a `signal_value` and a `confidence_band` derived from `lineup_state` (ADR 0016). Milestone 3 introduces the next operational reality. Signal emissions are not always final. The same pitch can produce multiple signal records over time as the upstream state evolves.

Three concrete sequences in the Phase 2 design produce a revision rather than a new signal:

1. The lineup confirms after the BATTER_UNCERTAIN window closes (ADR 0014). A pitch that was emitted with `confidence_band = reduced` and a projected batter is now re-evaluated against the confirmed batter. The signal_value may change, the confidence_band moves from `reduced` to `full`, and the system needs to declare that the previous emission was superseded.

2. A correction event for the underlying pitch arrives via the corrections.cdc topic (ADR 0003 era). The pitch's metadata changes (pitch_type, release_speed, plate location), which can change matchup-relevant features and therefore the signal_value. The previous emission must be superseded explicitly.

3. The Phase 3 reconciliation layer determines that a `suppressed` signal would have been correct based on canonical outcomes. The signal is not re-emitted to consumers, but it must be marked in the reconciliation ledger as a counterfactual hit so correction-rate metrics can be computed. This is a different sense of "revision" — the signal value does not change, but its operational status does.

Without a taxonomy, all three situations end up indistinguishable to downstream consumers. Alert orchestration cannot decide whether to re-fire. Dashboards cannot decide whether to update the previously shown value. Phase 3 reconciliation cannot separate "would have hit" from "actually hit" without re-deriving the cause from raw timestamps.

The Phase 2 scope anchor (`docs/phase2/README.md`) names three categories as concept seeds. This ADR commits to them as the durable taxonomy.

## Decision

A revision is a record that supersedes a previously emitted matchup signal for the same natural key (`game_pk`, `at_bat_number`, `pitch_number`). Every revision carries a `revision_type` field with exactly one of three values:

### material_update

The revised signal_value differs from the previous emission because an input changed. Two concrete subcauses share this category:

- A confirmation event resolved a previously uncertain lineup, and the actual batter differs from the projected batter. The signal_value computed against the actual batter differs from the placeholder value computed against the projected batter.
- A correction event changed a pitch's metadata (handedness inputs, fatigue context, or other matchup-relevant features) and the new signal_value differs from the previous.

A material_update is what alert orchestration cares about — it indicates a real change in the system's read of the matchup. Downstream consumers should treat a material_update as a new value to act on.

### baseline_confirmed

The revised signal_value is identical to the previous emission. The revision exists to record that the system now has higher confidence in the value, not that the value has changed.

The canonical case: a `reduced` confidence signal where the projected batter happened to match the actual batter once lineup confirmed. The value stays the same, but `confidence_band` moves from `reduced` to `full`. Phase 3 reconciliation needs to know this case happened — it is direct evidence that projection logic worked correctly for this matchup.

baseline_confirmed is signal about the signal: the system was right when it had reduced confidence, and Phase 3 can use this to calibrate.

### suppressed_by_governance

The revision exists only in the reconciliation ledger, not in the live signal stream. The previous emission was `suppressed` (lineup_state was `projected`) and did not drive any operational decision. Phase 3 reconciliation determined retrospectively that the signal_value would have been correct against the realized outcome.

suppressed_by_governance revisions answer the "should have fired" question Chad Corwin named on 2026-05-19. They never appear in the live signal stream that drives alerts — emitting them there would re-introduce the noise that governance suppression was designed to prevent. They live exclusively in the reconciliation marts that Phase 3 produces.

## Alternatives Considered

### Single boolean is_revision flag

Mark any non-initial emission as `is_revision = true` and let consumers compute the cause from timestamps and confidence_band transitions.

Rejected. Consumers cannot reliably re-derive the cause without joining against the lineup confirmation log, the corrections topic, and the reconciliation ledger. Three downstream consumers reproducing the same join means three places where bugs can diverge. Carrying the cause explicitly on the revision is cheap and load-bearing.

### Five-category taxonomy splitting material_update by cause

Split material_update into `material_update_lineup_confirmed` and `material_update_correction`, keeping the other two as-is.

Rejected for this milestone. Both subcauses produce the same downstream behavior: the signal_value changed, consumers should re-act. The cause is recoverable from the revision's source_event_id (which points to either a lineup_confirmation event or a correction_event) without inflating the taxonomy. If a future ADR finds that alert orchestration or reconciliation needs the distinction at category level, this ADR can be extended additively.

### Inline the taxonomy in confidence_band

Reuse `confidence_band` as the only emission marker and let consumers infer revision semantics from confidence_band transitions over time.

Rejected. `confidence_band` describes the current signal's confidence; revision_type describes the relationship between this emission and the previous one. Conflating them loses information in the suppressed_by_governance case, where the signal_value remained suppressed but the reconciliation ledger needs to record that it would have been right.

## Out Of Scope For This ADR

- The Avro schema for `MatchupRevisionEvent`. That belongs in the Milestone 3 implementation commits, where the schema lives next to the producer.
- The Kafka topic name for revisions. Provisional name `features.matchup.v1.revisions` is consistent with the existing `features.matchup.v1` topic, but the final name is implementation detail.
- The retention policy for revisions in the lakehouse. Phase 3 reconciliation determines how far back the ledger reaches; this ADR only specifies the taxonomy.
- Whether revisions are emitted by the same Flink job that produces the live signal (planned for 2026-06-20 per ADR 0016) or a separate revision-emitter job. That is a Phase 3 deployment topology decision.
- The exact computation that determines whether a baseline_confirmed revision is worth emitting. A pitch that projected the right batter purely by coincidence (e.g., the 9-hole spot in a stable lineup) is informative but cheap; one that projected through three walk-back layers is informative and expensive. Phase 3 may add a confidence-of-projection signal to weight these. Out of scope here.

## Consequences

- A new `revision_type` field is added to the matchup revision contract with allowed values `{material_update, baseline_confirmed, suppressed_by_governance}`. dbt tests enforce the allowed-values constraint at build time, matching the pattern established by `confidence_band` in ADR 0016.

- silver_matchup_signals continues to be the canonical record of initial signal emissions. A new model (likely `silver_matchup_revisions` in Milestone 3) will be the canonical record of revisions, joined on natural key.

- Alert orchestration consumes the live signal stream and the live revision stream. It re-fires only on `material_update`. `baseline_confirmed` and `suppressed_by_governance` never trigger alerts.

- Phase 3 reconciliation reads silver_matchup_signals + silver_matchup_revisions + the canonical outcomes mart. The should-have-fired ledger that Chad named is implemented by joining `suppressed_by_governance` revisions against canonical outcomes and computing the correction rate.

- The Phase 3 reconciliation mart can express three distinct metrics that are otherwise tangled: (a) accuracy on initial emissions where the system did fire, (b) accuracy on suppressed signals where the system held back, and (c) calibration of reduced-confidence emissions that became baseline_confirmed.

- The taxonomy is closed by design at three categories. If a fourth operational reality emerges (e.g., a signal becomes invalid because the underlying pitch is later deleted, not corrected), this ADR is extended explicitly rather than overloading existing categories.

## References

- ADR 0013: BATTER_UNCERTAIN state representation — `docs/adr/0013-batter-uncertain-state-representation.md`
- ADR 0014: Uncertainty window injection mechanism — `docs/adr/0014-uncertainty-window-injection-mechanism.md`
- ADR 0015: Projected batter source during uncertainty — `docs/adr/0015-projected-batter-source-during-uncertainty.md`
- ADR 0016: Matchup signal design — `docs/adr/0016-matchup-signal-design.md`
- Phase 2 scope anchor (taxonomy seeds) — `docs/phase2/README.md`
- Counterparty response naming the suppressed-signal ledger as load-bearing — `docs/mini_probe/2026_05_19_chad_response.md`
