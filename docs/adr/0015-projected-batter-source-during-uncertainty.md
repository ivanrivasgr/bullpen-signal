# ADR 0015 - Projected Batter Source During Uncertainty Window

- **Status:** Accepted
- **Date:** 2026-05-25

## Context

ADR 0013 established that pitch events emitted during the uncertainty window carry `lineup_state = uncertain` and `batter_id = projected_batter_id`. ADR 0014 established that the replay engine computes those projections and emits them at the source. Neither ADR specified how the projected batter is computed. This ADR closes that gap.

The decision needs to honor three constraints already imposed by earlier ADRs:

1. **Determinism.** ADR 0014 requires the replay engine to produce byte-identical output across runs with the same configuration. Any projection source that depends on external services with unstable availability would break this property.
2. **Statcast-only data surface.** Milestone 1 is scoped to data that already exists in the replay engine's input. Adding external feeds (depth charts from FanGraphs, RotoWire, MLB.com APIs) would scale the milestone beyond its 2-3 week target window.
3. **Fidelity to production.** ADR 0014 named "build the uncertainty from the source, not simulate it" as a load-bearing property. The projection has to be defensible as something a real baseball operations team would actually use as a baseline — not a placeholder that obviously isn't how real systems work.

The implicit question this ADR answers is: what does a real MLB operations team do when they need to project the batter facing a pitcher 75 minutes before first pitch, before the official lineup is posted? They do not pull from a single source. They build a hierarchy: official posting if available, otherwise the most recent confirmed lineup adjusted for known absences. This ADR encodes that hierarchy at the level of fidelity Milestone 1 can support without adding external dependencies.

## Decision

The projected batter for a pitch event during the uncertainty window is computed by the replay engine using a hierarchical lookup against Statcast-derived data already in the replay engine's input scope. The hierarchy has one primary source, two fallbacks, and one exception filter.

**Primary — Previous game lineup.** Look up the most recent game where the same team played, take that game's confirmed lineup, and use the batter at the corresponding lineup position as the projected batter.

**Fallback 1 — Last played game.** If no game exists for the team on the previous calendar day (off day, scheduled rest, postponement), walk backward day by day until the most recent game where the team played is found. Use that game's lineup. This handles the day-off case explicitly rather than letting the primary source silently fall back to an undefined state.

**Fallback 2 — Opening Day lineup.** For games in the first week of the season, when no prior game exists for the team in the current season, use the team's Opening Day starting lineup. This is the only structural fallback — it is intentionally narrow rather than reaching for prior-season data, which would introduce roster turnover noise.

**Exception filter — Injured List status.** Any player who was on the Injured List on the date of the projected game is removed from the candidate lineup and the order is recompacted, with the next-eligible position-player batter taking their slot. The IL-replacement choice uses the most recent appearance by another position player at that lineup slot in the same team's prior games as the recompaction rule.

The replay engine implements this as a pure function: given `(game_pk, team_id, lineup_position, projection_date)`, return `projected_batter_id`. The function is deterministic and the lookup tables are derived from the same Statcast input data that drives the rest of the replay engine.

## Alternatives Considered

### External depth chart source

Use a pre-game depth chart from an external provider (FanGraphs, RotoWire, MLB.com depth chart APIs) as the projection source. This is what a real operations team with vendor relationships would do for the freshest possible projection.

Rejected for Milestone 1. Two reasons. First, historical depth charts for retrospective replay are not trivially available — most providers archive current depth charts but not the depth chart as it was at a specific point in time, which is what backfill replay actually needs. Second, even where archived depth charts exist, integrating them requires a new ingestion path, new schema, new tests, and a dependency on third-party data availability for any replay run. The cost of that integration scales Milestone 1 past its 2-3 week target. If a calibrated archived depth chart source becomes available in a later milestone, this ADR can be extended to add it as the new primary source, with the current hierarchy demoted to fallback.

### Single-source previous game lineup

Use only the previous game's lineup with no fallback for off days or season-start cases, and no IL exception filter. Simpler to implement.

Rejected. The simplification produces obvious failure modes: NULL projections on every Opening Day, broken projections after any team off-day, and stale projections for any player who was IL'd between the previous game and the current one. A practitioner reading the ADR would recognize these as gaps that real systems handle. Leaving them unhandled would be a Senior-level decision dressed up as a Staff-level one.

### No projection during uncertainty window

Emit `batter_id = NULL` or a sentinel value during the uncertainty window, do not project at all.

Rejected. This contradicts ADR 0013, which explicitly chose a representation where `batter_id` carries the best available guess at all times and `lineup_state` carries the certainty metadata about that guess. Setting `batter_id = NULL` during uncertainty would collapse the two-column semantics back into a single-column representation, undoing the decision made in ADR 0013. It would also remove Phase 3's ability to evaluate how well the system projected during the uncertainty window — a dimension Chad Corwin's 2026-05-19 response named as relevant to the "should have fired" ledger.

## Out Of Scope For This ADR

- **Probabilistic projections.** This ADR returns a single projected batter, not a distribution over candidates. If a future milestone adds probabilistic semantics (as discussed and deferred in ADR 0013), the projection function's output type changes but the hierarchy of sources stays valid as the way to compute the modal candidate.
- **In-game lineup changes.** Pinch hitters, defensive substitutions, and double switches are handled by the live game feed once `lineup_state = confirmed`, not by this projection. The projection covers only the pre-confirmation window.
- **Cross-season backfill.** The Opening Day fallback explicitly does not reach into the prior season. Roster turnover between seasons is too large for prior-season lineups to be a defensible projection. Games before Opening Day data exists for a given season are out of scope for the replay engine until that season's Opening Day data lands.
- **Source of Injured List data.** The IL exception filter assumes IL roster transactions are available in the replay engine's input. The Statcast roster transactions endpoint is the planned source, but the exact integration path is implementation detail covered in the milestone plan, not in this ADR.

## Consequences

- The replay engine gains a `compute_projected_batter` function with the hierarchy described above. The function is pure, deterministic, and takes only inputs the replay engine already has access to.
- The replay engine gains a precomputation step: building a lookup table of `(team_id, game_date) -> lineup` from confirmed historical lineups, plus a `(player_id, date_range) -> on_il` lookup for the IL exception. Both are computed once per replay run from Statcast inputs.
- The projection function is testable in isolation. Unit tests can verify each layer of the hierarchy independently: previous game found, previous game not found but earlier game exists, no prior game in season, IL exception triggered and order recompacted.
- The projection is conservative by design. It will be wrong on any day where the manager makes a non-obvious lineup change (a planned rest, a hot streak promotion, a defensive matchup play). The frequency of those changes is empirical and will show up in the Phase 3 reconciliation as the gap between projected and confirmed batters during the uncertainty window.
- The Opening Day fallback creates a documented blind spot in the first week of each season's replay. Phase 3 reconciliation should expect higher projection-vs-confirmed gaps in that window and not interpret the gap as a model signal.
- Future replacement of the primary source (if depth chart archives become available) is mechanically simple: extend the hierarchy with a new layer above "previous game lineup". The hierarchy structure does not need to change.

## References

- ADR 0013: BATTER_UNCERTAIN state representation — `docs/adr/0013-batter-uncertain-state-representation.md`
- ADR 0014: Uncertainty window injection mechanism — `docs/adr/0014-uncertainty-window-injection-mechanism.md`
- Phase 2 scope anchor: `docs/phase2/README.md`
- Phase 2 milestone 1 plan: `docs/phase2/milestone_1_plan.md`
- Counterparty response naming Phase 3 reconciliation as load-bearing: `docs/mini_probe/2026_05_19_chad_response.md`
