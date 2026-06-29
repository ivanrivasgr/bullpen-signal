# BULLPEN SIGNAL — ROADMAP (self-directed)

> **How this is used (Claude reads this each session):**
> 1. Load the project brief (working rules + technical context) from the Claude
>    Project knowledge — it is kept there, not in git.
> 2. Read the STATUS section below: it states exactly where everything stands.
> 3. Take the NEXT OPEN STEP from the sequence. Do not ask "what should I do" —
>    the next step is already here. Produce its code and the bash block, Ivan
>    runs it and pastes the output, verify, and mark the step done by updating
>    the STATUS section.
> 4. The product decisions are ALREADY made below (DECISIONS). Do NOT re-ask
>    them. If one turns out to be wrong while implementing, then stop and flag
>    it — but the default is to execute against what was decided.
> 5. One step = one commit (or a few, reviewable). Audit + ruff before each.

---

## PRODUCT DECISIONS (made once — do not re-ask)

**Governing principle:** The dashboard defines the RESULT (the shape, what is
shown). The PROCESS that produces the data must be MLB-grade / Staff, NOT the toy
formulas in `synthetic_data.py`. Each signal comes from a verifiable source, not
an invented curve.

- **D1 — Leverage:** real Leverage Index (Tom Tango), derived from game state
  already in `silver_pitch_events` (inning, half, outs, base state, score diff).
  Published LI table carried as a seed. Not the synthetic `0.8 + pitch_idx/200`.
- **D2 — Fatigue:** real per-pitch signal from rolling velocity/spin/command
  deltas vs the pitcher's own in-game baseline. Components kept separate. Not the
  per-game aggregate in `silver_pitcher_game_fatigue`, not the synthetic weighting.
- **D3 — Matchup:** the real signal already built (`streaming.matchup_signals`
  vs `silver_matchup_signals`).
- **D4 — Reconciliation meaning:** all three signals computed by shared core. The
  streaming value uses data as of emission (projected lineup, partial history);
  the canonical value uses complete, corrected post-game data. The delta is the
  effect of late data and corrections — ADR 0001's thesis, applied to all three.
  No signal fabricates a streaming value that was never computed.
- **D5 — Alert orchestrator:** batch (`mart_alerts`). The dashboard shows a
  completed game; no real-time alerting required.
- **D6 — Classification threshold:** T = 0.10. reversed = opposite sign;
  softened = same sign and |canonical| < |streaming|*(1-T); escalated = same sign
  and |canonical| > |streaming|*(1+T); confirmed = same sign within T;
  confirmed_late = confirmed but the pitch carried is_late_arrival.

All six are recorded in ADR 0026.

---

## SEQUENCE (each step is a commit, in dependency order)

### STEP 1 — ADR 0026 (decisions written) — DONE
`docs/adr/0026-dashboard-reconciliation-scope.md` with D1-D6.

### STEP 2 — Real Leverage Index (D1) — DONE (5faee52)
- Seed: `dbt/seeds/leverage_index_table.csv` (LI by base-out state, with inning
  and score-diff adjustment; document the source in the ADR).
- Model: `dbt/models/silver/silver_leverage_index.sql` — one LI value per pitch
  from game state. As-of-emission and canonical versions.
- Test: not_null on the key; LI in a plausible range.
Commit: feat(dbt): leverage index signal from game state [ADR 0026]

### STEP 3 — Real per-pitch fatigue signal (D2) — DONE (31c88b4)
- Model: `dbt/models/silver/silver_fatigue_signal.sql` — rolling velo/spin/command
  vs the pitcher's baseline, per pitch, components separate.
- Test: not_null on the key; components in [0,1].
Commit: feat(dbt): per-pitch fatigue signal from rolling deltas [ADR 0026]

### STEP 4 — Unified long signal values
- Model: `dbt/models/marts/mart_signal_values_long.sql` — one row per
  (game_pk, at_bat, pitch, signal_name) with streaming_value and canonical_value
  for all three signals.
- Test: signal_name in {leverage, fatigue, matchup}; both values not_null.
Commit: feat(dbt): unified long signal values, streaming vs canonical

### STEP 5 — Batch alert orchestrator (D5)
- Model: `dbt/models/marts/mart_alerts.sql` — composes the three signals into
  alerts with composite_score, threshold, severity, rationale, alert_uid.
- Test: each alert has >=1 component signal; severity in the valid set.
Commit: feat(dbt): batch alert orchestrator over signal values [ADR 0026]

### STEP 6 — mart_signal_reconciliation (the dashboard table)
- Model: `dbt/models/marts/mart_signal_reconciliation.sql` — joins mart_alerts to
  mart_signal_values_long, produces the ReconciliationRow shape
  (alert_uid, signal, streaming_value, canonical_value, delta, classification)
  with the D6 classification.
- Test: classification in the five; delta = streaming - canonical.
Commit: feat(dbt): per-alert signal reconciliation mart [ADR 0026]

### STEP 7 — real_data.py (mirror of synthetic, reads DuckDB)
- `apps/dashboard/real_data.py` — same dataclasses, same functions, same return
  shapes as `synthetic_data.py`, reading `~/.bullpen/dbt.duckdb`. Where a piece
  has no real source (e.g. pitcher season splits), read what exists and leave the
  rest explicit/empty, not fabricated.
Commit: feat(dashboard): real_data reads marts from duckdb

### STEP 8 — Wire the dashboard
- `apps/dashboard/main.py` line 21: import synthetic_data -> import real_data.
  The render is untouched. Run it, verify it renders with real data.
Commit: feat(dashboard): wire dashboard to real data

### AFTER THE MILESTONE (registered, not part of it)
- Full-season calibration of the ADR 0016 placeholder magnitudes.
- Real streaming twins for leverage/fatigue if live alerting is wanted.
- start-flink.sh hardening (clear stale JARs).
- Kafka sink for the signal.
- Integration tests that hang against the stack.

---

## STATUS (the single source of truth — update every session)

**Last updated:** 2026-06-27
**main:** 31c88b4 — fatigue signal via Mahalanobis [ADR 0026]. Synced with origin.
**Stack:** docker compose up -d (Docker Desktop running).
**Tests:** 257 unit green; reconciliation 20/20; leverage 7/7; fatigue 2/2.

**Next open step:** STEP 4 (unified long signal values).

**Sequence progress:**
- [x] STEP 1 — ADR 0026
- [x] STEP 2 — Leverage Index
- [x] STEP 3 — Fatigue signal
- [ ] STEP 4 — Unified long signal values
- [ ] STEP 5 — Alert orchestrator
- [ ] STEP 6 — mart_signal_reconciliation
- [ ] STEP 7 — real_data.py
- [ ] STEP 8 — wire dashboard

**Last session notes:** STEPS 2 and 3 done. Leverage = Tango's published LI
chart (seed, mean 1.025 confirms faithful join). Fatigue = Mahalanobis distance
of velo/spin/command from each pitcher's fresh in-game baseline, per Dillon et
al. 2025 (Yankees team physician); verified fatigue rises late in long outings
(2.22 vs 1.57 baseline). Both computed identically for streaming and canonical
reads. Next: STEP 4, mart_signal_values_long joining all three signals
(leverage, fatigue, matchup) with streaming_value and canonical_value side by
side.
