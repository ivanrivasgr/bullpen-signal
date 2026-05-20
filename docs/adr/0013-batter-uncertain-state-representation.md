# ADR 0013 - BATTER_UNCERTAIN State Representation

- **Status:** Accepted
- **Date:** 2026-05-19

## Context

Phase 2 introduces matchup signal generation: who is pitching, who is batting, and how that matchup should affect the live signal. The Phase 2 scope anchor (`docs/phase2/README.md`) names a production constraint that the historical Statcast replay shape hides: lineups do not arrive as clean, complete inputs at pitch 1. Lineup confirmation lands 60 to 90 minutes before first pitch in the common case, and sometimes later. Until confirmation lands, the next batter is genuinely unknown.

The replay engine currently emits Statcast-shaped events where the batter is always known, because retrospective Statcast records are reconciled after the fact. Building matchup logic on top of that shape would silently assume a level of certainty that production will not provide.

Three concerns are load-bearing before implementation starts:

1. how `BATTER_UNCERTAIN` is encoded at the pitch-event grain
2. how downstream consumers (matchup signal, suppression logic, Phase 3 reconciliation) distinguish uncertainty from missingness
3. how the encoding survives a join against canonical batch outcomes in Phase 3 without forcing a counterfactual the data cannot answer

The third concern is the one Chad Corwin's 2026-05-19 response to the stationarity writeup made sharper. The reconciliation layer he named as the load-bearing instrument for governance only works if upstream state carries enough information to reconstruct "what did the system know when the pitch happened" versus "what did we learn later". A representation that collapses uncertainty upstream cannot be un-collapsed downstream.

## Decision

Add a column `lineup_state` to pitch events with enum values `{confirmed, uncertain, projected}`. The existing `batter_id` column carries the system's best guess at emission time: the projected batter during the pre-confirmation window, and the actual batter once lineup confirmation has landed. The `lineup_state` column records the epistemic status of that guess at the moment the event was emitted.

This separates the identity question (who) from the certainty question (how sure). Each is encoded in its own column with its own semantics. A pitch event during the uncertainty window has `lineup_state = uncertain` and `batter_id` set to the projected batter from the most recent depth chart or pre-game posting. A pitch event after lineup confirmation has `lineup_state = confirmed` and `batter_id` set to the confirmed batter. A pitch event emitted before any projection is available has `lineup_state = projected` with `batter_id` carrying whatever the source-of-projection returns.

The decision rule is: `batter_id` always carries the system's best available guess. `lineup_state` carries the metadata about that guess. Downstream consumers that don't care about uncertainty can use `batter_id` as before. Consumers that do care (matchup signal weighting, suppression policy, Phase 3 reconciliation) filter on `lineup_state` explicitly.

## Alternatives Considered

### Sentinel batter_id

Use a reserved batter_id value (e.g., `-1` or `NULL`) on pitch events emitted during the uncertainty window, with a companion boolean flag `batter_is_uncertain` to disambiguate from genuine data quality nulls.

Rejected. Sentinel values are a known anti-pattern that invite silent bugs where consumers forget to filter and the sentinel propagates into joins, aggregations, or features. The boolean flag pattern also duplicates state — `batter_id = -1` and `batter_is_uncertain = true` must always co-occur, and any code path that updates one without the other introduces incoherence. More importantly, the sentinel encoding throws away the projected batter. Phase 3 reconciliation against canonical batch outcomes loses the ability to reconstruct what the system believed at decision time, which is the exact bookkeeping Chad Corwin's 2026-05-19 response named as the load-bearing instrument for governance.

### Probabilistic representation

Replace `batter_id` with a distribution over candidate batters: a JSON or struct field like `batter_candidates: [{batter_id: 12345, prob: 0.7}, {batter_id: 67890, prob: 0.3}]`, with the confirmed case being a degenerate distribution.

Rejected for this milestone. The representation is theoretically the most expressive, but probabilistic semantics require a calibrated probability source. Until there is a defensible way to assign those probabilities, the distribution is theater — it looks rigorous but the numbers are arbitrary. Significantly more complex schema cost is paid by silver, by Phase 3, and by any reconciliation logic, in exchange for expressiveness that the project cannot yet honestly populate. If a calibrated source of batter probability emerges in a later milestone, a future ADR can extend `lineup_state` or layer probability information on top of the chosen representation without re-doing this decision.

## Out Of Scope For This ADR

- The source of projected lineups (depth charts, prior-day announcements, pre-game postings) is a separate decision. This ADR defines the representation; the source is documented in `docs/phase2/milestone_1_plan.md` and may merit its own follow-up ADR.
- Whether `BATTER_UNCERTAIN` should also be represented at the game-state level (pre-first-pitch uncertainty about starting pitcher matchups, for example) is deferred. This ADR scopes only to pitch-event-level batter uncertainty.
- Backfill of historical replay windows to include synthetic uncertainty windows is a replay-engine question, not a schema question. Covered separately in the milestone plan.

## Consequences

- `bronze.pitches` requires a schema migration to add the `lineup_state` column with the three-value enum. Migration is additive — existing consumers that don't reference the column continue to work, and `batter_id` semantics are preserved.
- The Avro schema for pitch events on Kafka requires a corresponding field addition. Schema Registry compatibility mode for the pitches subject will accept this as a backward-compatible change since the field has a default.
- The replay engine must learn to emit a non-confirmed `lineup_state` during synthetic uncertainty windows. The exact injection mechanism (source-side delay versus stream-side holdback) is decided in the milestone plan, not in this ADR.
- Downstream silver models that depend on `bronze.pitches` may want to filter or partition on `lineup_state`. None of them are required to do so — the default behavior of consuming `batter_id` as before remains valid for any consumer that explicitly does not care about uncertainty.
- Phase 3 reconciliation gains a clean filter: "evaluate decisions made while `lineup_state = uncertain` against the eventually-confirmed batter and the actual outcome". The counterfactual reconstruction Chad named is achievable without joining external roster transaction data, because the projected batter at decision time is preserved on the pitch-event row.
- The `projected` state value is provisioned but not required for Milestone 1. Milestone 1 can ship with only `{confirmed, uncertain}` populated, and the `projected` state becomes usable once a pre-game projection source is wired in. This avoids over-engineering while preserving the option.

## References

- Phase 2 scope anchor: `docs/phase2/README.md`
- Phase 2 milestone 1 plan: `docs/phase2/milestone_1_plan.md`
- External commitment driving the requirement: `docs/external_commitments.md` (`EXT-2026-04-29-001`)
- Counterparty response that sharpened the Phase 3 constraint: `docs/mini_probe/2026_05_19_chad_response.md`
