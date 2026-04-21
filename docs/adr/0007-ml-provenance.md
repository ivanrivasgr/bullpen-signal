# ADR 0007 — How machine learning fits in Bullpen Signal

- **Status:** Accepted
- **Date:** Phase 0

## Context

The question of whether and how to surface ML in this project is worth
deciding early and writing down. Adjacent projects in the same domain
(e.g., BaseballIQ) have faced legitimate critique when model outputs are
presented as "insights" without clear provenance or label definitions.
Bullpen Signal should not repeat that pattern.

The project's core thesis is about a dual-path architecture: streaming
gives you provisional signals fast, batch gives you canonical truth late,
and the reconciliation between them is the product. ML in this project
has to serve that thesis, not compete with it.

## Decision

Machine learning enters the system as a **signal calibration layer**, not
as a prediction engine.

Specifically:

1. **Fatigue score weights are learned**, not authored. Each component
   (velocity delta, spin delta, command, pitch count) carries a weight
   fit from historical data against an observable label: *a pitcher was
   removed within the next two batters for performance reasons, excluding
   planned bullpen days, double-switches, and injuries*.
2. **The target label is observed, never inferred.** No LLM-as-judge, no
   synthetic labeling, no "model of a model" constructions.
3. **Model provenance is visible but not foregrounded.** A short
   `Signal calibration` section at the end of the Live Dugout view,
   plus a single metadata line on each alert card (e.g., `model: fatigue_v1.2 · auc 0.74`).
4. **Model versioning is first-class.** Each alert record persists the
   model version that produced it. Reconciliation queries can filter
   or aggregate by model version.
5. **No predictive claims the system cannot defend.** The system does
   not predict win probability, game outcomes, or future pitches. It
   calibrates the mapping from observed state to an observable managerial
   decision.

## Alternatives considered

- **No ML mention in the UI.** Rejected. Without visible provenance,
  thresholds like 0.55 and 0.70 appear arbitrary and invite the exact
  critique we want to prevent.
- **Dedicated ML tab with feature importance, SHAP, confusion matrices.**
  Rejected. This is genuinely interesting content and it belongs in the
  Phase 5 Medium article, not in the operational dashboard. Elevating it
  in the dashboard inverts the project's thesis.
- **LLM-generated narrative insights over the data.** Rejected. The
  domain has well-understood statistical vocabulary. Text generation
  adds risk surface without adding analytical value. If a reader wants
  narrative, the case studies in `docs/case_studies/` are the place.

## Consequences

- The fatigue job cannot ship without its calibration artifact. The Flink
  job loads weights from a pinned Parquet file at startup; there is no
  fallback set of hardcoded weights in production code.
- Every alert becomes reproducible end-to-end: given the alert record,
  an auditor can retrieve the model version, the input snapshot, and
  recompute the score deterministically.
- Recalibration is a first-class operation with its own backtest suite.
  A PR that ships a new model version must include the backtest report
  and a signed-off `MODEL_CARD.md`.
- Phase 0 and Phase 1 dashboards do not include calibration panels.
  Calibration arrives in Phase 3 alongside reconciliation. Until the
  reconciliation layer exists, surfacing calibration quality has no
  grounding; it would be model cards without evidence.
