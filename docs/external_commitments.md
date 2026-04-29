# External Commitments

## Purpose

This file tracks public technical commitments that should not live only in
external threads, comments, or DMs.

Bullpen Signal is being built in public. When a practitioner gives feedback
that changes the roadmap, or when I publicly commit to testing a claim, the
commitment belongs in the repo. This keeps public claims tied to implementation
work, and makes it clear when a commitment is still open, delivered, withdrawn,
or intentionally deferred.

## How To Use This File

Each entry should capture:

- where the commitment came from
- who the counterparty was
- the exact commitment in one sentence
- the self-imposed deadline
- what the work will and will not deliver
- current status

This is not a planning document. Detailed implementation belongs in the
relevant phase docs, ADRs, issues, or code commits.

## Status Legend

- `open`: committed publicly, not started yet
- `in-progress`: work has started but output has not been delivered
- `delivered`: output was produced and shared or committed
- `withdrawn`: explicitly removed, with rationale

---

## EXT-2026-04-29-001 - Stationarity Probe For Suppressed Signal Governance

**Status:** open

**Date captured:** 2026-04-29

**Source:** LinkedIn comment thread on the Phase 1 announcement post

**Counterparty:** Chad Corwin, Founder & ML Systems Architect, Production MLB

**Public commitment:** Run a bounded replay-engine probe comparing activation
rate and evidence-gap distributions across two Statcast windows with different
roster-churn profiles, then share the result before Chad's late-May governance
review.

**Self-imposed deadline:** Share a mini-writeup before the end of May 2026,
targeting the week of 2026-05-18 through 2026-05-22 for the analysis run.

### Why This Exists

The thread surfaced a governance question that should not be lost: a fixed
threshold in parameter space can drift in operating-point space when the
population changes. Roster stabilization, role clarity, and market efficiency
can move the set of near-threshold cases even when the configured threshold
never changes.

The useful diagnostic may not be only which alerts fired. Suppressed decisions
near the threshold can show where the model wanted to move but governance did
not allow the signal to clear. An emissions-only orchestrator cannot see that
bucket.

### Scope

This probe will deliver:

- Two historical Statcast replay windows selected to have different
  roster-churn profiles.
- The same threshold logic applied to both windows.
- Activation rate comparison across the two windows.
- Evidence-gap distribution comparison across the two windows.
- A short writeup summarizing whether the observed differences look
  dimensionally sensitive to roster stabilization.

This probe will not deliver:

- A production-quality stationarity study.
- A claim about Chad's real population or forecast-of-record system.
- A replacement for scored flip results.
- A permanent governance policy for Bullpen Signal.
- A full Phase 3 reconciliation implementation.

### Downstream References

- Phase 1 closeout slot: `docs/phase1/milestone_3_closeout.md`
- Phase 2 scope anchor: `docs/phase2/README.md`
- Phase 3 scope anchor: `docs/phase3/README.md`
