# ADR 0028 - An Irresolvable Matchup Is Null, Not Zero

- **Status:** Accepted
- **Date:** 2026-07-08

## Context

The matchup signal is computed by `compute_signal_fields` in
`signals/matchup_core.py`, shared by the batch dbt model and the streaming
Flink job (ADR 0021). It looks the handedness matchup up in the calibrated
map (ADR 0027) and returns a scalar `signal_value`.

During the BATTER_UNCERTAIN window (ADR 0014) the system projects the batter
it believes is coming up (ADR 0015), and the reduced emission's signal is
computed from that projection, not from the batter who actually hit (ADR 0020).
When the projected player is absent from the `player_handedness` seed as a
batter, `derive_handedness_matchup` returns `None`, because a matchup with one
side unknown is not a usable signal. That part was already modelled correctly.

The defect was one layer down. `compute_signal_fields` resolved that `None`
with `CALIBRATED_SIGNAL_VALUES.get(handedness_matchup, 0.0)`, fabricating a
`0.0`. The calibrated map also carried an explicit `None: 0.0` entry making the
same substitution. That `0.0` was indistinguishable from a real computed
neutral value -- `S_vs_S` is a legitimate `0.0`. "Could not compute" and
"computed, and neutral" are different facts, and collapsing them behind the
same number is the sentinel anti-pattern this project already rejected in
ADR 0013 for `batter_id`.

### The observed failure

Forensic trace, game 745523, at-bat 3, pitches 1 and 2, on 2024-04-07. The
uncertainty window projected pitcher Jonathan Heasley (669169) as the batter
for the slot. Heasley exists in `player_handedness` only as a pitcher, so
`lookup_hand(669169, 'batter')` returned `None`, the projected matchup resolved
to `None`, and the reduced emission's `signal_value` was fabricated as `0.0`.

An important detail of the emission model makes these rows hard to read
directly. The row persists the identity columns of the *real* batter -- Ryan
Mountcastle (663624), a right-handed hitter -- so `batter_id = 663624` and
`handedness_matchup = 'L_vs_R'` against the left-handed pitcher. But the
reduced emission's `signal_value` was computed from the *projected* batter's
matchup, which was `None`. String and value come from different batters at
different moments in the pipeline. The projected batter that drove the value is
not persisted on the output row, so `handedness_matchup` alone cannot explain a
row's value: the table holds rows with identical `handedness_matchup = 'L_vs_R'`
carrying `-0.0097`, `-0.0052`, `0.0187`, and (before this fix) a fabricated
`0.0`.

Downstream, `mart_signal_values_long` picks the uncertain emission first, so the
fabricated `0.0` became the pitch's `streaming_value`. Against the canonical
value of `-0.0097` this is a non-zero delta, so the pitch entered the divergence
table. There the D6 classifier (ADR 0026) could not place it: `reversed`
requires both values non-zero, and `softened` / `escalated` require the two
values to share a sign under the `>= 0` convention, which a `0.0` streaming
value fails. The pitch fell through every predicate to the `else` branch and was
labelled `confirmed`. Two such pitches sat in the dashboard's divergence table
mislabelled as confirmed -- divergences by the inclusion filter, non-divergences
by the classifier, an incoherence with no correct reading, because the value
itself was never real.

The D6 predicates do not partition the value space when a value is exactly
`0.0`. Rather than widen the classifiers to special-case zero -- which would
change fixed reconciliation semantics (ADR 0026) to accommodate a fabricated
input -- the fix removes the fabrication at its source.

## Decision

An irresolvable matchup yields `signal_value = None`, not `0.0`.

1. `compute_signal_fields` looks the matchup up with
   `CALIBRATED_SIGNAL_VALUES.get(handedness_matchup)` and no default. A matchup
   that is `None`, or an unrecognized bucket string, yields
   `signal_value = None`. Its return type widens to
   `tuple[float | None, str, str]`. The `confidence_band` is unchanged: it still
   derives only from `lineup_state`.

2. The calibrated map holds exactly the nine handedness buckets and no `None`
   key. `None` is not a bucket with a neutral value; it is the absence of a
   computable one. The generator that writes the map is changed to match, so a
   regeneration reproduces the committed file.

3. `MatchupSignal.signal_value` widens to `float | None`. The
   `streaming.matchup_signals` Iceberg column, which was `required`, is evolved
   to optional so the `NULL` can land. ADR 0022 had specified nullability for
   the string fields on exactly this reasoning -- a player absent from the
   handedness seed -- but left `signal_value` required; this completes that
   intent.

4. Nothing downstream special-cases the value. In `mart_signal_values_long` a
   `NULL` `streaming_value` propagates to the reconciliation, where the
   divergence filter `ABS(streaming - canonical) > 0.0001` evaluates to `NULL`,
   not `TRUE`, so the pitch drops out of the divergence table as non-evaluable.
   That is the correct reading: the as-of-emission state for that pitch was "no
   computable signal", which is neither an agreement nor a divergence.

The double emission of ADR 0020 is untouched. An uncertain pitch with an
irresolvable projection still emits both rows; the message-plus-uncertain =
Iceberg-rows arithmetic is preserved. The stream is not filtered -- only the
value that was never computable is recorded as `NULL` instead of a fabricated
`0.0`.

## Consequences

- The two mislabelled `confirmed` rows leave the divergence table. Verified on
  the fourteen-date corpus: dataset divergences move from 432 to **430** (353
  reversed / 41 escalated / 36 softened, zero spurious confirmed);
  first-inning divergences from 337 to **335**. Alert counts (2302 total / 84
  action) and the anti-contamination invariant (`silver_pitch_events` = 53817)
  are unchanged -- they do not depend on this value. Zero action-grade alerts
  coincide with a divergence, as before.

- The prior contract (`None -> 0.0`) was asserted by unit tests, which means it
  was a deliberate choice, not an oversight. Those assertions encoded the
  defect. They are corrected here, not preserved: `TestUnknownHandednessMatchup`
  becomes `TestIrresolvableHandednessMatchup` and asserts `signal_value is
  None`; the calibration map test drops the `None`-key coverage; the streaming
  contract test `test_null_matchup_yields_neutral` becomes
  `test_null_matchup_yields_null_signal`. Per the project's first rule, the fix
  addressed the root cause and then corrected the tests that asserted the wrong
  thing -- the tests were not edited to pass.

- **A `not_null` test on `signal_value` is no longer possible, and this exposes
  a real observability gap.** Two dbt tests asserted `signal_value` is never
  null. They now fail by design. They cannot be narrowed with a `where` clause
  either: no persisted column distinguishes a row whose value came from an
  irresolvable projection from a row whose value came from a resolved one. Both
  carry `confidence_band = 'reduced'` and `lineup_state_at_emission =
  'uncertain'`; the projected batter that determined the value is not on the
  row. The tests are removed, with the reasoning recorded in the schema files.
  The correct repair is to persist the projected batter (or a
  `matchup_resolvable` flag) on the emission, which would make the null
  explainable from the row and restore a targeted `not_null ... where` test.
  That change touches the Avro contract, the bronze and silver chain, and the
  ADR 0022 output contract, so it is filed as debt rather than folded into this
  fix. Until then, the suite runs 123 tests rather than 125.

- The D6 classifiers are left exactly as they are. The zero-partition gap they
  contain is now unreachable in practice: with no fabricated `0.0`, the only
  path to a `0.0` streaming value is a genuine `S_vs_S`, which did not occur in
  the 2024 April dates and, if it did, would be a real neutral matchup rather
  than an uncomputable one. Whether to make the classifiers partition the zero
  case explicitly is a reconciliation-semantics question for a future ADR, not
  forced by this defect.

- `confidence_band` semantics are untouched. `suppressed` continues to mean a
  `projected` lineup state carrying a real calibrated value for Phase 3
  counterfactuals (the `mart_should_have_fired_ledger` still filters to
  `('reduced', 'suppressed')`); it is not overloaded to mean "irresolvable".
  Irresolvability is carried by a `NULL` value, orthogonal to the band.

## Alternatives considered

**Keep `0.0` and widen the D6 classifiers to treat an uncomputable `0.0` as
non-evaluable.** Rejected. It changes fixed reconciliation semantics (ADR 0026)
to accommodate a fabricated input, detects the condition downstream instead of
at its origin, and leaves a sentinel `0.0` in storage indistinguishable from a
real neutral value -- the exact ambiguity ADR 0013 rejected.

**Filter the irresolvable pitch out of the stream.** Rejected. It breaks the
ADR 0020 emission arithmetic and re-introduces the class of stream-side
filtering that the reconciliation exists to avoid: the divergence the product
reports must not be manufactured by dropping inconvenient emissions.

**Persist the projected batter before landing this fix, so the `not_null` test
could be narrowed instead of removed.** Rejected for sequencing, not on merit:
it is the right end state and is filed as debt. Threading `projected_batter_id`
through the Avro schema, bronze, silver, and the ADR 0022 output contract is a
change of its own, and holding the sentinel fix behind it would leave fabricated
`0.0` values in the reconciliation for longer than necessary.
