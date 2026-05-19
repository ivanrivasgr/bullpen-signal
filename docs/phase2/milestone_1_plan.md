# Phase 2 — Milestone 1: BATTER_UNCERTAIN state foundation

**Target window:** 2026-05-20 through 2026-06-05 (2-3 weeks)
**Phase 2 scope anchor:** `docs/phase2/README.md`
**Phase 3 alignment:** this milestone emits the state that Phase 3 reconciliation will consume.

## Purpose

Establish `BATTER_UNCERTAIN` as a first-class state in the matchup signal pipeline before any matchup logic is written. Without this foundation, every downstream model will silently assume historical replay data is production-shaped, which it is not.

This requirement comes from the LinkedIn comment thread captured in `docs/external_commitments.md` and is now reinforced by Chad Corwin's 2026-05-19 response to the stationarity probe, which named the reconciliation layer as the load-bearing instrument for the governance question — and the reconciliation layer cannot work if the matchup signal collapses uncertainty into fake certainty upstream.

## Scope

This milestone delivers:

1. ADR 0013 documenting the BATTER_UNCERTAIN state representation decision.
2. Schema definition in the bronze layer to carry lineup confirmation state per pitch event.
3. Replay engine modification to inject uncertainty windows that mimic production timing (lineup confirmation lands 60-90 min before first pitch, sometimes later).
4. Tests proving that downstream consumers see BATTER_UNCERTAIN correctly during the uncertainty window and the real batter after.

This milestone does NOT deliver:

- Matchup signal generation (next milestone).
- Revision taxonomy implementation (ADR 0014, next milestone).
- Any signal suppression logic (Phase 3).

## Decisions to make

### Decision 1: Representation (ADR 0013)

Three candidate options:
- Sentinel batter_id (e.g., -1 or NULL with a state flag).
- Separate column `lineup_state` ∈ {confirmed, uncertain, projected}.
- Probabilistic representation (distribution over candidate batters).

Each has different implications for Phase 3 reconciliation, which is the load-bearing constraint per Chad's 2026-05-19 response.

### Decision 2: Replay engine injection mechanism

Two candidate options:
- At replay-engine source: synthetic delay on lineup events.
- At Flink job level: holdback window on lineup confirmation messages.

### Decision 3: ADR numbering

Confirmed: BATTER_UNCERTAIN is ADR 0013. Revision taxonomy will be ADR 0014. The Phase 2 README references to 0008/0009 are historical and should be corrected when this milestone closes.

## Open question for Phase 3 (parked, not for this milestone)

How does the "should have fired" ledger distinguish a suppressed signal that would have been correct from one that would have been wrong, when the canonical batch outcome doesn't directly answer that counterfactual? This is the question I asked Chad on 2026-05-19. Park it. Phase 3 problem.

## Definition of done

- ADR 0013 merged.
- Schema reflects the new state in bronze.
- Replay engine produces realistic uncertainty windows.
- Integration test: a pitch event during the uncertainty window has BATTER_UNCERTAIN, a pitch event after confirmation has the correct batter.
- No matchup logic yet — that's the next milestone.
