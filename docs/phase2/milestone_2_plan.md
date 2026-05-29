# Phase 2 — Milestone 2: Matchup signal generation

**Target window:** 2026-06-02 through 2026-06-08
**Phase 2 scope anchor:** `docs/phase2/README.md`
**Depends on:** ADR 0013 (lineup_state), ADR 0014 (injection), ADR 0015 (projection)

## Purpose

Generate the first real matchup signal from pitch events that carry `lineup_state`. The signal must respect the BATTER_UNCERTAIN state: when `lineup_state = uncertain`, the matchup signal is emitted with reduced confidence or suppressed entirely depending on governance policy.

## Scope

This milestone delivers:

1. A new silver model `silver_matchup_events` derived from `silver_pitch_events` that exposes per-(pitch, pitcher, batter) matchup features: handedness matchup, recent batter performance vs pitcher type, pitcher fatigue context.
2. A signal generation function that emits `matchup_signal` events with an explicit confidence band that reflects `lineup_state`.
3. Tests covering: confirmed lineup → full-confidence signal; uncertain lineup → reduced-confidence signal; projected lineup → flagged for governance review.

This milestone does NOT deliver:
- Revision taxonomy implementation (next milestone, ADR 0016).
- Suppression policy enforcement (Phase 3).
- Reconciliation against canonical batch outcomes (Phase 3).

## Decisions to make this week

1. Schema of `silver_matchup_events` — what columns, what grain.
2. How confidence is encoded — single column, multi-column, or struct.
3. Whether the matchup signal is computed in dbt (batch) or as a Flink job (streaming). Probably dbt for milestone 2, Flink later.

## Definition of done

- silver_matchup_events materializes from silver_pitch_events.
- Confidence band column reflects lineup_state.
- Integration test runs end-to-end on the existing bronze → silver pipeline with the new model.
- Phase 3 has enough state on the matchup_events table to evaluate reconciliation against canonical outcomes.
