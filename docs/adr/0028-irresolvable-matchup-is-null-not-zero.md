# ADR 0028 - An Irresolvable Matchup Is Null, Not Zero

- **Status:** Accepted
- **Date:** 2026-07-07

## Context

The matchup signal is computed by `compute_signal_fields` in
`signals/matchup_core.py`, shared by the batch dbt model and the streaming
Flink job (ADR 0021). It looks the handedness matchup up in the calibrated
map (ADR 0027) and returns a scalar `signal_value`.

A pitch's matchup can be irresolvable. During the BATTER_UNCERTAIN window
(ADR 0014) the system projects the batter (ADR 0015); if the projected
player is absent from the `player_handedness` seed, `derive_handedness_matchup`
returns `None`, because a matchup with one side unknown is not a usable
signal. `derive_handedness_matchup` already models this correctly — it
returns `None`. The defect was one layer down: `compute_signal_fields`
resolved that `None` with `CALIBRATED_SIGNAL_VALUES.get(handedness_matchup,
0.0)`, fabricating a `0.0`. The calibrated map also carried an explicit
`None: 0.0` entry making the same substitution.

That `0.0` was indistinguishable from a real computed neutral value
(`S_vs_S` is a legitimate `0.0`). "Could not compute" and "computed, and
neutral" are different facts, and collapsing them behind the same number is
the sentinel anti-pattern this project already rejected in ADR 0013 for
`batter_id`. The consequence surfaced in the reconciliation dashboard.

### The observed failure

Forensic trace, game 745523, at-bat 3, pitches 1 and 2. The uncertainty
window projected pitcher Jonathan Heasley (669169) as the batter for the
slot. Heasley exists in `player_handedness` only as a pitcher, so
`lookup_hand(669169, 'batter')` returned `None`, the matchup resolved to
`None`, and the reduced emission's `signal_value` was fabricated as `0.0`
with confidence band `reduced` (the band derives from `lineup_state`, so it
looked like an ordinary uncertain read).

Downstream, `mart_signal_values_long` picks the uncertain emission first, so
the fabricated `0.0` became the pitch's `streaming_value`. Against the
canonical value of `-0.0097` this is a non-zero delta, so the pitch entered
the divergence table. There the D6 classifier (ADR 0026) could not place it:
`reversed` requires both values non-zero, and `softened` / `escalated`
require the two values to share a sign under the `>= 0` convention, which a
`0.0` streaming value fails. The pitch fell through every predicate to the
`else` branch and was labelled `confirmed`. Two such pitches sat in the
dashboard's divergence table mislabelled as confirmed — divergences by the
inclusion filter, non-divergences by the classifier, an incoherence with no
correct reading, because the value itself was never real.

The D6 predicates do not partition the value space when a value is exactly
`0.0`. Rather than widen the classifiers to special-case zero — which would
change fixed reconciliation semantics (ADR 0026) to accommodate a fabricated
input — the fix removes the fabrication at its source.

## Decision

An irresolvable matchup yields `signal_value = None`, not `0.0`.

1. `compute_signal_fields` looks the matchup up with
   `CALIBRATED_SIGNAL_VALUES.get(handedness_matchup)` and no default. A
   matchup that is `None`, or an unrecognized bucket string, yields
   `signal_value = None`. Its return type widens to
   `tuple[float | None, str, str]`. The `confidence_band` is unchanged: it
   still derives only from `lineup_state`.

2. The calibrated map holds exactly the nine handedness buckets and no
   `None` key. `None` is not a bucket with a neutral value; it is the
   absence of a computable one.

3. `MatchupSignal.signal_value` widens to `float | None`. The Flink
   emission UDTF already types the column as a nullable `FLOAT`, so a `None`
   serialises to a `NULL` in the `streaming.matchup_signals` Iceberg column.
   No schema change; the streaming `source_not_null` tests do not cover
   `signal_value`.

4. Nothing downstream special-cases the value. In
   `mart_signal_values_long` a `NULL` `streaming_value` propagates to the
   reconciliation, where the divergence filter `ABS(streaming - canonical) >
   0.0001` evaluates to `NULL`, not `TRUE`, so the pitch drops out of the
   divergence table as non-evaluable. That is the correct reading: the
   as-of-emission state for that pitch was "no computable signal", which is
   neither an agreement nor a divergence.

The double emission of ADR 0020 is untouched. An uncertain pitch with an
irresolvable projection still emits both rows; the message-plus-uncertain =
Iceberg-rows arithmetic is preserved. The stream is not filtered — only the
value that was never computable is recorded as `NULL` instead of a fabricated
`0.0`.

## Consequences

- The two mislabelled `confirmed` rows leave the divergence table. Dataset
  divergences move from 432 to 430 (353 reversed / 41 escalated / 36
  softened, 0 spurious confirmed); first-inning divergences from 337 to 335.
  Alert counts (2302 total / 84 action) and the anti-contamination invariant
  (`silver_pitch_events` = 53817) are unaffected — they do not depend on this
  value.

- The prior contract (`None -> 0.0`) was asserted by tests, which means it
  was a deliberate choice, not an oversight. Those assertions encoded the
  defect. They are corrected here, not preserved: `TestUnknownHandednessMatchup`
  becomes `TestIrresolvableHandednessMatchup` and asserts `signal_value is
  None`; the calibration map test drops the `None`-key coverage and the
  `test_none_fallback_is_neutral` case. Per the project's first rule, the fix
  addressed the root cause and then corrected the tests that asserted the
  wrong thing — the tests were not edited to pass.

- The D6 classifiers are left exactly as they are. The zero-partition gap
  they contain is now unreachable in practice: with no fabricated `0.0`, the
  only path to a `0.0` streaming value is a genuine `S_vs_S`, which did not
  occur in the 2024 April dates and, if it did, would be a real neutral
  matchup rather than an uncomputable one. Whether to make the classifiers
  partition the zero case explicitly is a reconciliation-semantics question
  for a future ADR, not forced by this defect.

- `confidence_band` semantics are untouched. `suppressed` continues to mean a
  `projected` lineup state carrying a real calibrated value for Phase 3
  counterfactuals (the `mart_should_have_fired_ledger` still filters to
  `('reduced', 'suppressed')`); it is not overloaded to mean "irresolvable".
  Irresolvability is carried by a `NULL` value, orthogonal to the band.

## Alternatives considered

**Keep `0.0` and widen the D6 classifiers to treat an uncomputable `0.0` as
non-evaluable.** Rejected. It changes fixed reconciliation semantics
(ADR 0026) to accommodate a fabricated input, detects the condition
downstream instead of at its origin, and leaves a sentinel `0.0` in storage
indistinguishable from a real neutral value — the exact ambiguity ADR 0013
rejected.

**Filter the irresolvable pitch out of the stream.** Rejected. It breaks the
ADR 0020 emission arithmetic and re-introduces the class of stream-side
filtering that the reconciliation exists to avoid: the divergence the product
reports must not be manufactured by dropping inconvenient emissions.
