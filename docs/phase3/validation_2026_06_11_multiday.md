# Phase 3 Reconciliation — Multi-Day Validation, 2026-06-11

## Why this exists

Through 2026-06-10 the reconciliation loop was validated on a single day
(2024-04-15) with the uncertainty rate forced to 1.0. That proves the
mechanism but not the system: a single day at an artificial rate hides
bugs that volume and real sequencing expose. This run subjects the
pipeline to fourteen consecutive real game dates at the real uncertainty
rate (0.15, not forced), accumulating into bronze without wiping between
days, then builds the marts once and runs the producer once. The harness
is committed at scripts/validate_reconciliation_multiday.py.

## What held

- 53,817 pitches over 14 days (2024-04-02 .. 2024-04-15) replayed,
  materialized, and built with zero errors.
- dbt build silver + marts: PASS=75, ERROR=0 at this volume.
- The revision producer processed 53,817 groups idempotently and emitted
  375 revisions with 78 no-ops. The watermark advanced once; a second run
  would emit zero, as the batch-producer contract requires.
- At the real 0.15 rate, 480 pitches landed in the uncertainty window
  (0.9% of all pitches) — only the opening seconds of late-lineup games
  qualify, which matches the ADR 0014 framing. 453 of the 480 carried a
  projection.

The system works at scale. The findings below are about the data, not
the pipeline.

## Finding 1 — 27 null projections are correct degradation, not a bug

Of 480 uncertain pitches, 27 had no projection. All 27 belong to a single
game on 2024-04-02: Minnesota (142) at Milwaukee (158). Both teams' first
cached lineup is 2024-04-02 — neither played on 2024-04-01, and 04-02 was
their opening day, so there was no previous-game lineup and no prior
opening day to fall back to. The ADR 0015 hierarchy correctly returned no
projection, the pitches were still tagged uncertain, and the observed
batter was preserved. This is the graceful-degradation path behaving
exactly as designed. It is recorded here so the count is not mistaken for
a defect later.

## Finding 2 — correction rates are not yet calibration-grade

The reconciliation summary produced these rates by handedness matchup:

- R_vs_L: n=171, rate=0.33
- R_vs_R: n=168, rate=0.47
- R_vs_S: n=55, rate=0.53
- L_vs_R: n=37 (35 evaluable), rate=0.54
- L_vs_L: n=30, rate=0.73
- L_vs_S: n=19, rate=0.00

Only R_vs_R and R_vs_L have sample sizes that begin to support an
estimate. The rest are thin. L_vs_S at 0.00 over 19 pitches does not mean
left-handed pitchers never need correction against switch hitters; it
means nineteen observations happened to include no correction. Feeding
any of these into the ADR 0016 placeholder magnitudes now would be
calibrating on noise. The summary is structurally correct and computes
the right quantity — it simply needs season-scale volume before the
numbers carry weight.

## Finding 3 — three handedness buckets never appeared

The signal placeholder table defines nine handedness matchups, including
the three where a switch hitter bats (S_vs_R, S_vs_L, S_vs_S). None
appeared in this window: no switch hitter happened to fall inside an
uncertainty window across these fourteen April days. The buckets are
supported end to end but unexercised by this slice of data. A
full-season run would populate them.

## Conclusion

The reconciliation pipeline is sound at volume: it ingests, materializes,
builds, and produces revisions correctly over 14 days and 53k pitches.
What it does not yet have is enough data for the correction rates to mean
anything. Calibration of the ADR 0016 magnitudes is therefore deferred
until a full-season replay produces sample sizes that justify it; doing
it on 14 days would dress up noise as signal. The honest state of Phase 3
is: mechanism complete and validated, calibration pending volume.

## Reproducing

    python -m scripts.validate_reconciliation_multiday \
        --start-date 2024-04-02 --end-date 2024-04-15 \
        --cache-start 2024-04-01

Then materialize bronze, run dbt build --select silver marts
--full-refresh, and run the revision producer. The numbers above are
deterministic for seed 42.
