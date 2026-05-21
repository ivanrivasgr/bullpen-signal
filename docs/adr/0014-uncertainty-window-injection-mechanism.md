# ADR 0014 - Uncertainty Window Injection Mechanism

- **Status:** Accepted
- **Date:** 2026-05-21

## Context

ADR 0013 established that pitch events carry a `lineup_state` column with values `{confirmed, uncertain, projected}` to represent the production reality that lineup confirmation lands 60 to 90 minutes before first pitch, sometimes later. The representation defines what is emitted. This ADR defines how the uncertainty window gets produced in the first place when the replay engine is reproducing historical Statcast windows that — by their retrospective nature — already contain the resolved batter on every pitch event.

Two concerns are load-bearing for this decision:

1. The system must be deterministic. Two runs of the same replay over the same window must produce the same output. Replay-based testing, regression checks, and reconciliation in Phase 3 all depend on this property.

2. The uncertainty window must be genuine. The system must not know who the batter will be during the uncertainty window, then hide that information at emission time. Hidden information is not the same as missing information. Phase 3 reconciliation cannot honestly evaluate suppressed decisions against canonical outcomes if the upstream uncertainty was simulated from data that was already resolved.

A third concern is conceptual hygiene: the replay engine should produce a stream that looks as close as possible to what the production stream will look like when MLB game feeds replace synthetic replay. The closer the shapes match, the less downstream code has to change when production cutover happens.

## Decision

The uncertainty window is injected at the replay-engine source. The replay engine emits two coordinated streams per game: pitch events and lineup events. Lineup events are scheduled with realistic timing — the lineup confirmation for a given game lands at a configurable offset before first pitch, with a default distribution centered around 75 minutes prior, occasionally late (after first pitch in a small percentage of simulated games to mirror production edge cases).

Pitch events emitted before the lineup confirmation for that game carry `lineup_state = uncertain` and `batter_id = projected_batter_id`, where the projected batter is computed from the most recent depth chart or pre-game projection available to the replay engine. Pitch events emitted at or after the lineup confirmation carry `lineup_state = confirmed` and `batter_id = confirmed_batter_id`.

The Flink job does not maintain holdback state for lineup events. It receives whatever the replay engine emits and writes it to `bronze.pitches` as-is. The `lineup_state` field is treated as opaque data by the streaming layer, not as a signal that triggers behavior in the job.

All timing is controlled by the replay engine's deterministic clock. The offset distribution for lineup confirmation timing is seeded by the replay run identifier, so two runs of the same replay with the same configuration produce byte-identical output.

## Alternatives Considered

### Flink holdback window

The replay engine continues to emit events as it does today — every pitch event with a resolved batter. The Flink job introduces a holdback window on lineup events: when a lineup confirmation arrives, it is buffered for a configurable duration before being released to the downstream sink. During the holdback period, pitch events that flow through the job are rewritten with `lineup_state = uncertain` even though the replay engine emitted them with the resolved batter.

Rejected for three reasons:

First, determinism is compromised. The duration of the holdback as experienced by any given pitch event depends on the wall-clock timing of the Flink job's processing — backpressure, parallelism, taskmanager restarts, and checkpoint barriers all introduce variance. Two runs of the same replay can produce different outputs at the boundary of the holdback window. This is unacceptable for a system that needs to be replay-tested.

Second, the uncertainty is not genuine. The Flink job has the resolved batter in hand and is choosing to mask it. The information exists upstream of the emission point. Phase 3 reconciliation against canonical batch outcomes will produce numbers that look like they answer "what did the system know at decision time" but actually answer "what did the system choose to reveal at decision time" — a different question, and the difference is systematic bias rather than random noise.

Third, the streaming layer accumulates state and complexity for a problem that is fundamentally a data generation concern, not a streaming concern. Holdback windows mean checkpointed state, recovery semantics, and integration tests that must control Flink timing — all to simulate a property the replay engine could produce directly.

### Hybrid approach (replay engine emits projection, Flink validates timing)

A variant where the replay engine emits both the projected batter and the confirmed batter on every pitch event, and the Flink job decides at emission which to use based on a holdback timer.

Rejected. This combines the costs of both approaches — replay engine complexity to compute projections plus Flink state to enforce timing — without resolving the determinism issue. It also forces every pitch event to carry two batter identifiers, which complicates the schema beyond what ADR 0013 selected.

## Out Of Scope For This ADR

- The source of projected batters during the uncertainty window (depth charts, pre-game lineup announcements, prior-day projections) is a data source decision separate from the injection mechanism. Documented in `docs/phase2/milestone_1_plan.md`. May warrant its own follow-up ADR once a specific projection source is selected.
- The exact distribution of lineup confirmation timing offsets (mean, variance, late-arrival tail) is a configuration concern, not an architectural one. Defaults are set in code and can be tuned without changing this ADR.
- Handling of in-game lineup changes (defensive substitutions, pinch hitters) is out of scope for Milestone 1. Those events have different timing properties and will be addressed in a later milestone if they prove necessary for the matchup signal.

## Consequences

- The replay engine gains a lineup event stream alongside its existing pitch event stream. Both streams are coordinated by the replay engine's deterministic clock and share a common run identifier for seeded reproducibility.
- The replay engine gains a projected-batter computation step. For Milestone 1, this can be a simple lookup (most recent confirmed lineup from the prior game, or last known starting lineup for the team). More sophisticated projection sources can be substituted later without changing the injection architecture.
- The Flink job remains stateless with respect to lineup uncertainty. It receives `lineup_state` and `batter_id` on each event and persists them. No holdback timers, no buffered lineup state, no checkpoint complexity around this concern.
- Replay determinism is preserved. Two runs of the same replay with the same configuration produce byte-identical output to `bronze.pitches`. This is required for regression testing and for Phase 3 reconciliation to be reproducible.
- Production cutover from replay-engine source to live MLB game feeds becomes a swap at the source layer only. The downstream stream shape (pitch events with `lineup_state` and `batter_id`) does not change. The Flink job, silver models, and Phase 3 reconciliation are insulated from the cutover.
- Testing strategy clarifies. Unit tests verify the replay engine produces correctly-timed lineup events and correctly-tagged pitch events. Integration tests verify the Flink job persists what it receives. Each layer has a single concern.

## References

- ADR 0013: BATTER_UNCERTAIN state representation — `docs/adr/0013-batter-uncertain-state-representation.md`
- Phase 2 scope anchor: `docs/phase2/README.md`
- Phase 2 milestone 1 plan: `docs/phase2/milestone_1_plan.md`
- Counterparty response sharpening the Phase 3 constraint: `docs/mini_probe/2026_05_19_chad_response.md`
