# Phase 3 Scope Anchor

Phase 3 focuses on reconciliation between the streaming path and the canonical
batch path. It is where Bullpen Signal answers which version of a signal was
actually used, why it changed, and whether governance thresholds drifted as the
population changed.

This README is a scope anchor, not a complete plan. Detail will be added when
Phase 3 begins, approximately mid-June 2026.

## Reconciliation Taxonomy

Phase 3 reconciliation should use four categories:

- `confirmed`: the streaming signal matched the later canonical view.
- `reversed`: the streaming signal was invalidated by the later canonical
  view.
- `escalated`: the later canonical view showed the original signal was too
  weak and should have been stronger.
- `suppressed_but_warranted`: the signal did not emit because governance
  suppressed it, but retrospective evidence shows it should have fired.

The fourth category is the important addition. An emissions-only orchestrator
cannot see false negatives. If the system only logs fired alerts, it loses the
most diagnostic bucket: cases where the model approached or crossed a useful
boundary but the governance layer did not allow the signal through.

## Threshold Operating-Point Drift

A threshold pinned in parameter space can drift in operating-point space when
the population changes. For example, a fixed cutoff can behave differently as
rosters stabilize, roles become clearer, or market efficiency improves. The
configuration did not move, but the set of games near the threshold did.

Phase 3 governance should monitor the operating point, not only the configured
parameter. The question is not just "did the threshold change?" The better
question is "did the population around the threshold change?"

## Pending ADRs

- ADR 0010: Reconciliation taxonomy with should-have-fired category
- ADR 0011: Threshold operating-point drift monitoring

## Inputs From Phase 1 Closeout

The stationarity mini-probe tracked as `EXT-2026-04-29-001` in
`docs/external_commitments.md` should be treated as an input to Phase 3 work.
It will not prove the governance design, but it should help decide whether the
threshold drift question is worth deeper implementation.
