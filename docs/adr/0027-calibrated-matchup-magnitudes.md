# ADR 0027 - Calibrated Matchup Magnitudes

- **Status:** Accepted
- **Date:** 2026-07-05

## Context

ADR 0016 shipped the matchup signal with placeholder magnitudes keyed on handedness only and deferred calibration until a full-season pull could support it. The Phase 3 multi-day validation (docs/phase3/validation_2026_06_11_multiday.md) re-affirmed that bar: correction rates over fourteen days were structurally correct but too thin to carry weight, and calibrating on them would dress up noise as signal.

Two developments make calibration due now.

First, the full-season pull exists: 711,898 regular-season pitches from 2024, pulled day by day into monthly parquets (infra/data_prep/pull_statcast_season.py). That is the season-scale volume the Phase 3 standard named.

Second, analysis of the dashboard's reconciliation data exposed a structural limit of the placeholder map. Under the placeholder values, each pitcher hand can reach exactly one positive and one negative signal value (R: +0.05 / -0.10; L: +0.08 / -0.10), so every visible projection error crosses zero. The D6 classification (ADR 0026) could therefore only ever produce confirmed or reversed rows -- softened and escalated were unreachable by construction, not by sample size. More replay volume could never surface them.

## Decision

### Magnitudes from the delta method of The Book

League platoon splits are computed with the delta method of The Book (Tango, Lichtman, Dolphin): within-batter wOBA differences between opposite-side and same-side plate appearances, weighted by the harmonic mean of each batter's PA against either pitcher side, aggregated per batter-handedness group, with switch hitters as their own group.

A per-bucket league aggregate was evaluated first and rejected on evidence: it reproduces the lineup-composition selection that platooning managers create (who faces whom is not random), and on two half-month windows it produced an inverted LHB split (-0.0086). The within-batter delta removes that selection. On the full season it measured RHB +0.0194 (The Book reference, 2000-2004 data: +0.017) and LHB +0.0374 (reference +0.027; a 2013 measurement of the same quantity found +0.035). Both splits positive, LHB larger than RHB -- the emergent structure the published literature predicts, recovered from raw data.

### Centering onto the ADR 0016 sign convention

The published quantity is one split per batter side. Mapping it onto the existing sign convention (positive = pitcher advantage) is this project's translation, and it is documented as such: each group's split is centered on the league-neutral baseline, so the same-side bucket gets +split/2 and the opposite-side bucket -split/2; the switch-hitter delta (wOBA vs RHP minus wOBA vs LHP) is centered the same way onto R_vs_S / L_vs_S. No magnitude is invented -- every map value is a measured split divided symmetrically.

### Delivery: a generated runtime module and the seed CSV from one run

infra/data_prep/build_matchup_calibration.py emits two outputs in a single run: dbt/seeds/matchup_calibration.csv (the measured buckets with sample sizes and provenance -- the audit trail) and signals/matchup_calibration.py (the complete runtime map). signals/matchup_core.py imports CALIBRATED_SIGNAL_VALUES from the generated module; the placeholder dict is gone. A unit test (tests/unit/signals/test_matchup_calibration.py) pins the module to the seed row by row, so the runtime signal and the audit trail cannot diverge silently.

The switch-pitcher buckets (S_vs_R, S_vs_L, S_vs_S) had no 2024 data. They extend the measured map by the reasoning the original placeholder documented -- a switch pitcher picks the favorable side -- so S_vs_R mirrors R_vs_R, S_vs_L mirrors L_vs_L, and S_vs_S is neutral. The generated module marks each of them uncalibrated.

### Consequence for the reconciliation, and the streaming history

With the calibrated map, each pitcher hand reaches two same-sign values (R: +0.0097 and +0.0052; L: -0.0097 and -0.0052), a magnitude ratio of ~0.54 -- far outside the D6 tolerance band. Softened and escalated become reachable classifications. The streaming history in Iceberg was emitted under the placeholder map, so the 2024-04-02 replay is re-run with the calibrated core, and both updated seeds land in DuckDB together with the dbt rebuild, so the batch and streaming sides of the reconciliation carry the same map.

## Alternatives Considered

### Per-bucket league aggregates

Rejected on evidence, as above: a bucket aggregate measures roster usage, not the matchup effect.

### Per-batter splits with regression to the mean

The Book's next refinement: individual batter splits regressed toward the league split by sample size. Deferred as an additive extension -- it needs per-batter regression constants and a wider signal contract (per-batter values instead of nine buckets). The league-level map lands first; this ADR does not preclude the extension.

### Loading the seed CSV at import time

Rejected: matchup_core is deliberately stdlib-only with no I/O so it can be imported in any runtime, including the Flink container, where path resolution is not guaranteed. A generated module travels with the package.

### Keeping the placeholders and adding replay volume

Rejected: the unreachable D6 classes are structural to the placeholder map's value set, not a sample-size artifact. Volume enriches what the map already expresses; it cannot change what the map can express.
