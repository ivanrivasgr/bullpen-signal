# Fatigue threshold stationarity — two 2024 windows

**Date:** 2026-05-13
**Cohort:** 293 pitchers with ≥1 appearance in both windows
**Script:** `scripts/mini_probe/compute_stationarity.py`
**Outputs:** `data/processed/mini_probe/` (gitignored, regenerable)

## Context

The current fatigue logic in `silver_pitcher_game_fatigue.sql` buckets each (game, pitcher) row by pitch count: low (<25), medium (25–49), high (≥50). The thresholds were set deliberately and noted as arbitrary in the Milestone 2 closeout, with the assumption that they would be revisited under governance. Before that conversation happens, I wanted a cheap check on whether the activation rates these thresholds produce are stable across windows of comparable workload but different roster composition. If the bucket assignments drift materially between two such windows, the static thresholds may not survive a roster shift and the 'deliberately arbitrary' label in the closeout doc would no longer be defendible.

## Method

Two 15-day windows from the 2024 MLB regular season:

- **Window A — April 1–15, 2024.** Early season, fluid rosters (post-spring training cuts, injury fill-ins, call-ups).
- **Window B — September 1–15, 2024.** Late season, rosters mostly settled, no trade deadline activity.

Same calendar duration controls for sample size. Same season controls for rule changes and season-level effects. The window pair was chosen to maximize the difference in roster churn while holding everything else as constant as I could.

Inclusion: any pitcher with at least one appearance in both windows. Pitchers appearing in only one window were dropped — no comparison possible. Cohort = 293 pitchers.

The Python bucketing replicates the dbt CASE WHEN exactly (low <25, medium 25–49, high ≥50), so the activation rates below are the same ones the silver model would produce on these windows.

## Results

### Activation rate by bucket per window

Rows are (game, pitcher) appearances, not pitchers. The denominator is total appearances in the window.

| Bucket | April (n=1,077) | September (n=1,102) | Δ (pp) |
|---|---|---|---|
| low (<25) | 57.6% | 60.5% | +2.9 |
| medium (25–49) | 15.5% | 14.3% | −1.2 |
| high (≥50) | 26.9% | 25.1% | −1.8 |

Aggregate activation rates are within ~3pp across windows. The shape of the distribution holds: roughly 60/15/25 in both windows. At the population level, the static thresholds look stable.

### Per-pitcher shift in % of high-bucket appearances

For each of the 293 pitchers, I computed pct_high in April and pct_high in September, then took the absolute difference.

| Statistic | Value |
|---|---|
| Mean shift | 8.75 pp |
| Median shift | 0.0 pp |
| Max shift | 100.0 pp |
| Pitchers with shift > 20pp | 14.3% |

Median of zero means most pitchers don't move at all — they sit in the same bucket window to window. The mean is pulled by a long tail: 14% of pitchers shift more than 20 percentage points in their high-bucket rate, and at least one pitcher swings from 0% to 100%. Worth noting that pitchers with one or two appearances in a window can hit extreme shift values mechanically (one outing flips the percentage), so the tail is partly a small-N artifact, not a pure stationarity finding.

### Bucket reassignment (modal bucket per window)

Using the modal bucket per pitcher per window:

- **Stable (same modal bucket in both):** 237 / 293 = 80.9%
- **Reassigned (different modal bucket):** 56 / 293 = 19.1%

Direction of the 56 reassignments:

| Direction | Count | % of reassigned |
|---|---|---|
| medium → low | 21 | 37.5% |
| low → medium | 14 | 25.0% |
| high → medium | 8 | 14.3% |
| high → low | 6 | 10.7% |
| low → high | 5 | 8.9% |
| medium → high | 2 | 3.6% |

35 of the 56 reassignments (62.5%) move toward a *lower* bucket in September. That's consistent with the small aggregate drop in high-bucket activation between April and September, but the asymmetry is more visible at the pitcher level than at the population level.

## Findings

The aggregate activation rates are stable within ~3 percentage points across the two windows. By that measure, the static thresholds pass.

The per-pitcher view is less clean. About one in five pitchers in the cohort changes modal bucket between windows, and 14% shift their high-bucket rate by more than 20 percentage points. The direction of bucket reassignment is asymmetric — more pitchers move toward lower-fatigue buckets in September than toward higher ones — which I'd expect from a late-season cohort that has lost the most-worked relievers to injury or workload management, but I haven't verified that mechanism here.

So: thresholds are stable in the aggregate, less stable per pitcher, and the per-pitcher instability has a the drift moves in the direction you'd expect if the underlying population is shifting rather than with threshold mis-calibration. That's the distinction worth surfacing in the governance review — drift in *who* shows up at high fatigue can look like threshold drift in a population-level report, when it's really roster turnover.

## Caveats

- Two windows is not a robustness study. It's a sanity check.
- Single year (2024). Rule changes, pitch clock effects in its second season, and league-level pitch usage trends are all confounders that a multi-year version of this probe would need to address.
- 15-day windows leave many pitchers with very few appearances. Per-pitcher shift statistics are noisy at low N and the max shift of 100pp is mechanically possible with one or two appearances per window.
- The modal-bucket method hides within-pitcher variance. A pitcher who is 51% low and 49% high in one window and 49% low / 51% high in the next reads as a bucket reassignment even though their behavior barely moved.
- This is a synthetic probe in the sense that the threshold values themselves were arbitrary to begin with — I'm testing the stability of an arbitrary partition, not the validity of that partition. Stability and validity are different questions.

## Open question

If activation rates drift materially between windows of similar workload distribution, what is the recommended response — adaptive thresholds tied to a rolling baseline, or hold the static thresholds and treat drift as a signal of population shift? This probe doesn't try to answer that. The aggregate numbers here don't force the question, but the per-pitcher numbers suggest it's worth answering before the governance review settles on a permanent threshold policy.

## Reproducibility

python scripts/mini_probe/compute_stationarity.py
Outputs: `data/processed/mini_probe/` (gitignored). Source CSVs: `activation_rates.csv`, `per_pitcher_shift.csv`, `shift_summary.csv`, `bucket_reassignment.csv`.
