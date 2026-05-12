# Mini-probe — Synthetic stationarity for Chad Corwin's late-May review

**Target delivery:** 2026-05-22 (Friday) — writeup shared a few days before Chad's review.
**Scope:** validate that the fatigue threshold logic (low <25, medium 25-49, high ≥50) produces stable activation rates across two MLB windows with different roster-churn profiles. If activations drift materially between windows of similar workload distribution, the static thresholds are an operating-point trap and the closeout's "deliberately arbitrary" claim becomes a vulnerability rather than a deferred decision.

## Decisions

### Window selection
- **Window A (low churn):** September 1-15, 2024. Late season, rosters mostly settled, no trade deadline activity.
- **Window B (high churn):** April 1-15, 2024. Early season, rosters fluid (post-spring training cuts, injury replacements, call-ups).

Rationale: same calendar duration (15 days) controls for sample size. Different position in the season controls for roster volatility. Same year (2024) controls for rule changes and season-level effects.

Fallback if 2024 data is incomplete: use 2023 with same window definitions.

### Pitcher inclusion
- Include pitchers with at least 1 appearance in BOTH windows. This is the comparable cohort.
- Exclude pitchers who only appear in one window (no comparison possible).
- Expected cohort size: 200-350 pitchers (rough estimate, refine after fetching data).

### Metrics computed per window

For each window, compute one row per (game_pk, pitcher_id):
- pitch_count
- fatigue_bucket (apply current thresholds: low <25, medium 25-49, high ≥50)

Then aggregate per pitcher_id across the window:
- N_games_played
- N_pitches_total
- pct_appearances_in_low
- pct_appearances_in_medium
- pct_appearances_in_high

### Comparison metrics (cross-window)

For the cohort that appears in both windows:
- **Activation rate per bucket:** % of (game_pk, pitcher_id) rows in each bucket per window. Compare A vs B.
- **Per-pitcher bucket distribution shift:** for each pitcher, compare pct_in_high(window A) vs pct_in_high(window B). Report mean absolute difference, median, distribution.
- **Bucket reassignment rate:** % of pitchers who moved one or more buckets between windows (e.g., medium in A, low in B).

### Output for Chad

Single markdown file at `docs/mini_probe/2026_05_22_chad_stationarity_writeup.md`:
- 1 paragraph context (what was tested and why)
- 1 table: activation rate by bucket per window (3 buckets × 2 windows = 6 cells)
- 1 table: per-pitcher distribution shift (mean, median, max, % > 20pp shift)
- 1 paragraph findings (what the numbers say about threshold stability)
- 1 paragraph caveats (sample size, single-year, two windows is not a robustness study)
- Link to script that reproduces all numbers

Length target: ~600 words. Not a paper, not a slide deck. A defensible note Chad can read in 5 minutes and probe further if he wants.

## Open question to surface in writeup (not resolve)

If activation rates drift materially between windows of similar workload distribution, what's the recommended response — adaptive thresholds tied to a rolling baseline, or hold the static thresholds and accept drift as a signal of population shift? This is Chad's question to answer in the governance review, not mine to resolve in the probe.

## Implementation notes (for Tuesday)

- Data source: pybaseball (https://github.com/jldbc/pybaseball) statcast_pitcher() or statcast() pull by date range.
- Storage: dump raw Statcast windows to `data/raw/statcast_2024_april.parquet` and `data/raw/statcast_2024_september.parquet`.
- Compute: standalone script `scripts/mini_probe/compute_stationarity.py`. Does NOT need to integrate with dbt or Iceberg. This is analysis, not pipeline.
- Reuse: the fatigue threshold logic from `dbt/models/silver/silver_pitcher_game_fatigue.sql` — replicate the CASE WHEN in Python so the writeup can claim the exact same logic was applied.

## NOT in scope for this mini-probe
- Reconciliation taxonomy validation (Chad's earlier framework — separate scope).
- Threshold drift over multiple seasons (would require 3+ years of data).
- Recommendation of adaptive thresholds (premature without more windows).
