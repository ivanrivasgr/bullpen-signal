# Phase 3 Closeout — Reconciliation Loop

- **Status:** Closed
- **Closed:** 2026-06-12
- **Started:** 2026-06-04 (ADR 0017 revision taxonomy)
- **Duration:** 9 days

## What Phase 3 Set Out To Do

The scope anchor (`docs/phase3/README.md`) framed Phase 3 as reconciliation:
answering which version of a signal was actually used, why it changed, and
whether governance thresholds drifted as the population changed. Its central
addition was the should-have-fired bucket — the false negatives an
emissions-only orchestrator cannot see.

Phase 3 delivered the reconciliation loop end to end: the system now records,
for every uncertain decision, what it projected, what actually happened, and
whether the projection held or was overturned once the truth arrived. The
should-have-fired ledger and reconciliation summary are populated from real
replay data and validated at volume.

## What Was Delivered

### Reconciliation marts and taxonomy — ADRs

| SHA | Title |
|-----|-------|
| `2a526a8` | docs(adr): record revision taxonomy [ADR 0017] |
| `201345c` | docs(adr): document would_have_been_correct as heuristic [ADR 0018] |
| `7d4bac5` | docs(adr): decide how revisions are emitted when uncertainty resolves [ADR 0019] |
| `c46900a` | docs(adr): record dbt double-emission resolution, supersede 0019 mechanism [ADR 0020] |

### Reconciliation marts (the triangle)

| SHA | Title |
|-----|-------|
| `09378f4` | feat(phase3): canonical outcomes mart + should-have-fired ledger |
| `25068f2` | feat(phase3): reconciliation summary mart aggregating the ledger |

### Revision emitter and producer

| SHA | Title |
|-----|-------|
| `6cc7557` | feat(phase3): revision emitter for matchup signal updates |
| `c8bafad` | feat(phase2): MatchupRevisionEvent schema + publisher integration |
| `fd4f6a5` | feat(phase3): batch producer for matchup signal revisions |

### Uncertainty activation and the ground-truth-preservation chain

| SHA | Title |
|-----|-------|
| `bc906e7` | feat(phase3): expose --uncertainty-rate to activate BATTER_UNCERTAIN |
| `189baae` | feat(phase3): preserve observed batter, record projection separately |
| `111d517` | feat(phase3): thread team_id to activate batter projection |
| `37fb353` | feat(phase3): emit two signals per uncertain pitch to close the revision loop |

### Validation and reproducibility

| SHA | Title |
|-----|-------|
| `7622cc4` | test(phase3): validate reconciliation over 14 days at real uncertainty rate |
| `e62ea1f` | perf(replay): enable pybaseball on-disk cache for statcast pulls |
| `(this commit)` | docs(phase3): closeout |

## Metrics

| Metric | Value |
|--------|-------|
| Unit tests | 190 |
| dbt models (silver + marts) | silver_pitch_events, silver_matchup_events, silver_matchup_signals, mart_canonical_outcomes, mart_should_have_fired_ledger, mart_reconciliation_summary |
| dbt build (silver + marts) | PASS=75, ERROR=0 |
| ADRs created | 0017, 0018, 0019, 0020 |
| ADRs superseded | 0019 mechanism, by 0020 |
| Kafka topics added | `features.matchup.v1.revisions` |
| Reference data added | `team_abbreviations.csv` (30 teams, derived from observed game data) |
| Multi-day validation | 53,817 pitches / 14 days / 375 revisions emitted |

## Architectural Decisions

**Inference never overwrites observation (ADR 0020).** The original uncertainty
window overwrote `batter_id` with the projected batter, destroying the observed
truth and making reconciliation impossible to compute downstream. The fix:
`batter_id` is always observed; a nullable `projected_batter_id` carries the
inference. This is the load-bearing correction of Phase 3.

**Resolution via dbt double emission, not replay re-emission (ADR 0020,
superseding 0019).** ADR 0019 proposed the replay emit the resolution.
Implementation showed signals are generated in dbt, not the replay. An uncertain
pitch now emits two signals in dbt — reduced from the projected handedness, full
from the real handedness — and the revision producer compares the pair. The
intent of 0019 stands; its mechanism was corrected.

**Revisions turn on handedness, not batter identity.** Two different batters who
share a handedness produce the same signal_value and therefore no revision. This
is why the validated run emitted 43 revisions and 16 no-ops over 59 uncertain
pitches (single-day), rather than matching the projected-vs-real batter split.

**team_id derived from observed game data, not StatsAPI fileCode.** Statcast
abbreviations differ from StatsAPI for four teams (LAA/AZ/LAD/WSH vs
ANA/ARI/LA/WAS). The abbreviation map is derived by joining the lineup cache and
the Statcast parquet on (game_pk, side), so the correspondence comes from the
games themselves. Hand-typing or trusting fileCode would have silently dropped
four large-market teams from the join.

**would_have_been_correct is a documented heuristic, not a calibrated metric
(ADR 0018).** Sign-only, magnitudes and leverage unweighted. The reconciliation
summary computes the right quantity; the numbers are not yet calibration-grade.

## What Was NOT Delivered (Out of Scope)

| Item | Disposition |
|------|-------------|
| Calibration of ADR 0016 placeholder magnitudes | Deferred — needs full-season volume; 14 days gives noise in thin buckets (validation doc `validation_2026_06_11_multiday.md`) |
| Threshold operating-point drift monitoring | Anchor-listed (README), not implemented; the stationarity probe (EXT-2026-04-29-001, delivered) informs whether it is worth deeper work |
| Streaming Flink reconciliation job | Later milestone; the batch dbt path is the current implementation |
| Switch-hitter-batting handedness buckets (S_vs_R, S_vs_L, S_vs_S) | Supported end to end, unexercised by the April validation window |

## Reconciliation Between Anchor And Implementation

The scope anchor anticipated a four-category taxonomy
(`confirmed/reversed/escalated/suppressed_but_warranted`) and ADRs 0010/0011.
Implementation diverged honestly. The taxonomy that shipped is ADR 0017's
`material_update/baseline_confirmed/suppressed_by_governance`, and the ADRs
landed as 0017–0020 rather than 0010/0011 (those numbers remain historical
gaps). The anchor's central idea — capturing what governance suppressed, the
false-negative bucket — is preserved in the should-have-fired ledger. The
operating-point-drift monitoring the anchor described was not built; it remains
a candidate for future work, now informed by the delivered stationarity probe.

## Known Technical Debt

**Calibration is pending volume, by decision.** The reconciliation summary is
structurally complete and computes real correction rates, but only R_vs_R and
R_vs_L reach sample sizes that support an estimate over 14 days. Calibrating the
ADR 0016 magnitudes now would dress noise as signal. The methodology is
documented; the data pull is the blocker.

**The reconciliation marts read batch dbt output, not a streaming source.** The
revision producer publishes to Kafka, but the marts are built from
silver_matchup_signals in DuckDB. The streaming reconciliation path is a later
milestone.

**No switch-hitter coverage in the validation window.** The three S_vs_*
batting matchups are supported but never appeared in 14 April days. A
full-season run would exercise them.

## Lessons Learned

**Verifying the code before writing prevented building on a wrong design twice.**
ADR 0019 assumed the replay generates signals; the code showed dbt does. Reading
the actual model before implementing caught it. Separately, the ground-truth
destruction was found by checking what `apply_uncertainty_window` did to
`batter_id` rather than trusting the summary that said projection was threaded.

**An ADR can be superseded within days, and that is healthy.** ADR 0019 was
written and corrected by ADR 0020 two days later, once implementation exposed
its flawed mechanism. The decision record shows the design maturing against
reality rather than hiding the correction.

**Deriving reference data from observed data beats typing or trusting an API.**
The team abbreviation map came out correct for all 30 teams, including the four
Statcast-specific abbreviations, because it was joined from the games rather than
hand-entered or pulled from StatsAPI fileCode.

**Single-day testing at a forced rate hides what volume exposes.** The 14-day
run at the real rate surfaced the one game with no previous-day lineup (27 null
projections, correct degradation) and made plain that the correction rates are
not yet calibration-grade — neither visible in the single-day forced-rate demo.

## Next (Placeholder)

No firm commitment exists for what follows Phase 3 or its start date. Candidates,
none dated:

- Full-season Statcast pull to give calibration-grade volume, then calibrate the
  ADR 0016 magnitudes against real correction rates.
- Streaming Flink reconciliation job (the matchup/leverage/alert jobs are
  currently README-only scaffolding).
- Operating-point-drift monitoring described in the Phase 3 anchor.

The only external commitment on record (EXT-2026-04-29-001) is delivered. There
is no outstanding public deadline.
