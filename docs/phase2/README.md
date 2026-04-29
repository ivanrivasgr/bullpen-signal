# Phase 2 Scope Anchor

Phase 2 focuses on matchup signal generation: who is pitching, who is batting,
and how that matchup should affect the live signal. The key production
constraint is that lineups do not arrive as clean, complete inputs at pitch 1.
The system must represent uncertainty explicitly instead of pretending the
historical Statcast replay shape is the production shape.

This README is a scope anchor, not a complete plan. Detail will be added when
Phase 2 begins, approximately mid-May 2026.

## Design Requirements

- Represent `BATTER_UNCERTAIN` as a first-class state. Production lineup
  confirmation can land 60-90 minutes before first pitch, sometimes later.
  The matchup signal must not collapse "unknown next batter" into a fake known
  batter just because historical replay data is already cleaned. This
  requirement comes from the LinkedIn comment thread captured in
  `docs/external_commitments.md`.

- Track revision taxonomy as a concept seed: `material_update`,
  `baseline_confirmed`, and `suppressed_by_governance`. These categories are
  not implemented yet. They are listed here because Phase 2 is where signal
  revisions are generated, even though reconciliation analysis belongs in
  Phase 3.

## Pending ADRs

- ADR 0008: Revision taxonomy for matchup signal updates
- ADR 0009: BATTER_UNCERTAIN state representation

## Notes

The Phase 2 plan should preserve a clear boundary between:

- signal generation
- governance suppression
- reconciliation against canonical batch outcomes

Do not write the reconciliation layer in Phase 2. Phase 2 should emit enough
state for Phase 3 to evaluate what happened.
