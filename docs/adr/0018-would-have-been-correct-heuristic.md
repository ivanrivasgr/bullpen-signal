# ADR 0018 - Heuristic for would_have_been_correct in the Should-Have-Fired Ledger

- **Status:** Accepted
- **Date:** 2026-06-06

## Context

Commit `09378f4` introduced `mart_should_have_fired_ledger` with a column `would_have_been_correct` that classifies each suppressed or reduced-confidence matchup signal as a counterfactual hit, miss, or unknown against the realized at-bat outcome. The classification is needed for Phase 3 reconciliation — the should-have-fired ledger Chad Corwin named as load-bearing on 2026-05-19 is only useful if downstream consumers can ask "of the decisions the system held back on, how many would have been right."

The realized outcome comes from `mart_canonical_outcomes`, which buckets raw Statcast events into a closed enum of ten result_types. The signal_value comes from `silver_matchup_signals`, which today emits placeholder magnitudes per ADR 0016 — the values encode the conventional baseball intuition that opposite-handed matchups favor the batter and same-handed matchups slightly favor the pitcher, but they are not calibrated against historical outcomes.

Two design constraints collide:

First, the ledger must produce a usable correction-rate metric today, before Phase 3 has accumulated enough outcomes to calibrate the signal_value magnitudes. Without a usable metric, the ledger is shape-only and Chad's reconciliation question stays unanswered.

Second, any classification that calls itself "correct" while resting on uncalibrated placeholder values risks misleading downstream consumers into treating the correction rate as a calibrated number. ADR 0013 already rejected the probabilistic representation of `lineup_state` for exactly this reason. ADR 0016 rejected numeric confidence for the same reason. Importing the trap into the ledger would undo that discipline.

The ledger needs a `would_have_been_correct` definition that is useful today, declared as a heuristic, and replaceable when calibration arrives.

## Decision

`would_have_been_correct` is computed as a documented heuristic, not a calibrated metric. The function is closed and intentionally simple:

- If `signal_value > 0` (signal points toward pitcher) AND `result_type IN ('strikeout', 'ground_out', 'fly_out', 'other')` → TRUE.
- If `signal_value < 0` (signal points toward batter) AND `result_type IN ('single', 'double', 'triple', 'home_run', 'walk', 'hit_by_pitch')` → TRUE.
- If `signal_value = 0` (neutral signal) → NULL. There is no correctness claim to evaluate.
- If `result_type IS NULL` (at-bat outcome not yet in the canonical mart) → NULL. The signal predates the outcome.
- Otherwise → FALSE.

The heuristic is honest about three of its limitations, declared here rather than discovered later:

### Limitation 1: 'other' is treated as pitcher-favorable

The 'other' bucket captures any Statcast event outside the named categories — sacrifice bunts, catcher interference, fielder's choice with no out recorded, and so on. The heuristic counts these as pitcher-favorable because most events in 'other' resolve the at-bat without a hit. This is a defensible approximation but not always correct (catcher interference advantages the batter, for example). Treating 'other' as NULL would be safer but would systematically exclude edge cases from the correction rate, which biases the metric. Treating it as pitcher-favorable keeps the metric honest at the cost of a small known error.

### Limitation 2: The signal_value magnitudes are not calibrated

The heuristic only looks at the sign of `signal_value`, not the magnitude. A signal at +0.05 (R_vs_R placeholder) is treated identically to a signal at +0.50, even though the second should imply much higher confidence in a pitcher-favorable outcome. Until ADR 0016's placeholder values are replaced with calibrated magnitudes from Phase 3 reconciliation, sign-only classification is the most the heuristic can defend.

### Limitation 3: Outcome semantics are not weighted

A strikeout and a weak fly-out both count as pitcher-favorable. A single and a home run both count as batter-favorable. The heuristic ignores leverage, runners on base, and the magnitude of the outcome's value (a strikeout with bases loaded is a much bigger pitcher win than one with the bases empty). Phase 3 reconciliation will eventually compute correction rates weighted by win probability added (WPA) or expected runs, but that requires a leverage mart that does not exist today.

## Alternatives Considered

### Compute a calibrated correction probability per row today

For each row, look up the empirical correction rate of similar matchups (same handedness, same fatigue bucket) in the canonical outcomes mart and emit a probability instead of a boolean.

Rejected. The empirical base rates require enough outcome data to compute reliably per matchup type, which is exactly what Phase 3 reconciliation will accumulate over weeks of replay runs. Computing them today against the 48 at-bats in the local stack would produce numbers with one or two significant figures of precision and high variance. Phase 3 calibration is the right vehicle for this, not a placeholder dressed up as calibration.

### Treat the heuristic's output as a probability, not a boolean

Emit `correctness_score` ∈ [0, 1] instead of `would_have_been_correct` ∈ {TRUE, FALSE, NULL}. Even with placeholder signal magnitudes, the function could produce continuous values by scaling against signal_value.

Rejected for the same reason ADR 0016 rejected numeric confidence. A probability that downstream consumers will read as calibrated, when in fact it rests on placeholder magnitudes, is worse than an honest boolean. The boolean signals "I am a heuristic" by its shape; a probability hides its nature.

### Defer the column entirely until Phase 3 calibration

Ship the ledger without `would_have_been_correct` and let Phase 3 add the column when calibration is ready.

Rejected because the ledger without that column cannot answer Chad's question. The ledger would record decisions the system held back on, but downstream consumers would have to build their own correctness logic to compute the correction rate — three downstream consumers means three places where the heuristic can diverge, none of them documented in the lakehouse. Centralizing the heuristic in the mart with explicit documentation is better than dispersing it.

## Out Of Scope For This ADR

- The actual calibration logic that will replace this heuristic. That is Phase 3 reconciliation work and will be its own ADR (likely 0020 or later) when the calibration model lands.
- The Phase 3 reconciliation pipeline that aggregates the ledger into correction rates over time. The ledger is per-row; the aggregation is mart-level work that comes after.
- Leverage-weighted correctness. Requires a leverage mart that does not exist. Out of scope until that mart lands.
- The handling of corrections.cdc events that may rewrite at-bat outcomes after the fact. Today the canonical outcomes mart reads silver_pitch_events at full-refresh time and does not separately reconcile against corrections. A follow-up ADR will address that path when corrections become operational.

## Consequences

- `mart_should_have_fired_ledger.would_have_been_correct` ships as a boolean with NULL for unevaluable rows. dbt tests do not enforce specific value distributions; the heuristic's output is data-dependent.
- Downstream consumers that compute correction rates from the ledger are responsible for treating NULL values explicitly (filter, propagate, or count separately). The mart documentation in `_marts.yml` will note this expectation in a future commit.
- When Phase 3 calibration arrives, the heuristic is replaced in place. The column name `would_have_been_correct` stays stable; only its definition changes. Consumers that joined against the boolean keep working; consumers that need calibrated probability migrate to whatever new column the calibration ADR introduces.
- The Phase 3 reconciliation aggregation, when it lands, will use this ledger as input. The aggregation will compute base rates by lineup_state and confidence_band, which then feed back into the calibration of signal_value magnitudes in `signals/matchup_signal.py`. This closes the loop the placeholder magnitudes opened in ADR 0016.

## References

- ADR 0013: BATTER_UNCERTAIN state representation — `docs/adr/0013-batter-uncertain-state-representation.md`
- ADR 0016: Matchup signal design — `docs/adr/0016-matchup-signal-design.md`
- ADR 0017: Revision taxonomy for matchup signal updates — `docs/adr/0017-revision-taxonomy.md`
- Counterparty response naming the should-have-fired ledger as load-bearing — `docs/mini_probe/2026_05_19_chad_response.md`
- Commit introducing the ledger — `09378f4`
