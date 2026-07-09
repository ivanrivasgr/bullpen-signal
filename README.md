# Bullpen Signal

A dual-path decision engine for pitcher removal. A streaming path computes signals live, under realistic noise; a batch path recomputes them from the complete, corrected record. The product is the reconciliation between the two: every pitch where the real-time read differed from canonical truth, classified and explained.

## The thesis

In a live game, the real-time system decides on information as of emission: projected lineups, late arrivals, events that are corrected afterwards. The batch path recomputes hours later against the complete record. The difference between the two reads -- the delta -- is not a system error. It is the honest measure of what it cost to decide in real time on incomplete information.

The reconciliation dashboard is the product. A regression in the reconciliation is a regression in the thesis. That is why the stream's noise -- duplicates, late arrivals, corrections -- is preserved and reported, never filtered so the two paths agree artificially.

## What the data said

Across 14 game dates and 53,817 pitches, the corpus produced a finding that was not designed:

- **All streaming-vs-canonical divergence lives in innings 1 and 2**, before lineups are confirmed: 430 divergent pitches (353 reversals, 41 escalations, 36 softenings), 335 of them in the first inning. Zero past the second.
- **Removal alerts fire in innings 4 through 6**, when the pitcher has thrown enough to fatigue and the batting order is long settled.
- **The two phases barely overlap.** Of 84 action-grade alerts, exactly zero land on a divergent pitch. The 18 coincidences that exist are all info- or warning-severity.

The real-time path takes its information risk early, on uncertain lineups, and makes its replace calls late, on firm data. That is the kind of finding a front-office analyst would report, and it emerged from the reconciliation rather than from a hypothesis.

## The three signals

Every signal comes from a published source or is derived verifiably from the data. Nothing is invented.

**Leverage** -- Tom Tango's published Leverage Index, loaded as a 3,696-state seed and verified cell by cell against the source tables. Each pitch maps to its game state: inning, half, bases, outs, score difference. An emergent validation: the mean LI across all 53,817 pitches is 1.025, the property the index has by construction.

**Fatigue** -- per-pitch mechanical deviation via Mahalanobis distance from the pitcher's own fresh baseline (his first 15 pitches of the game), over velocity, spin, and command. The method follows Dillon et al. (2025), *Orthopaedic Journal of Sports Medicine*. Documented adaptation: three of the paper's five features, because the feed does not carry arm angle, extension, or acceleration. Pitcher-games under 15 pitches yield NULL rather than a fabricated baseline.

**Matchup** -- handedness magnitudes calibrated on the full 2024 regular season (711,898 pitches, 181,116 plate appearances) with the delta method of *The Book* (Tango, Lichtman, Dolphin): within-batter wOBA differences weighted by the harmonic mean of each batter's plate appearances against either pitcher side. The emergent check the method predicts -- both platoon splits positive, left-handed batters larger than right -- comes out of the run, not into it. This is the one signal with two genuinely different sources: the streaming emission under lineup uncertainty against the batch-canonical value.

## The alert orchestrator

The three signals compose into pitcher-removal alerts following the published decision literature: **decline** (fatigue) x **situation** (leverage) x **familiarity** (times through the order). The TTO term is continuous, with no hard third-time-through cutoff, per Brill et al. (2023). Thresholds are anchored in published sources: Tango's leverage bands (medium 0.85, high 2.0) and the paper's fatigue percentiles (p90 ~ 3.2, p95 ~ 4.0, where p95 is its outlier threshold). Severities: info, warning, action.

On the corpus: 2,302 alerts, of which 84 are action-grade, across only 50 of 1,527 pitcher-games -- selective, as a removal call should be.

## Architecture

```
Statcast parquets ── replay engine (deliberate noise) ──> Kafka (Avro + Schema Registry)
                                                             │
                            ┌────────────────────────────────┴───────────────┐
                            │                                                │
                     Flink streaming job                             Iceberg bronze
                     (as-of-emission signal)                                 │
                            │                                          dbt silver
                            │                                     (pitch events, leverage,
                            │                                      fatigue, matchup signals)
                            │                                                │
                            │                                             marts
                            │                                   (alerts, signal values,
                            │                                     reconciliation)
                            └────────────────────────────────┬───────────────┘
                                                             │
                                                   Streamlit dashboard
                                          (live dugout / canonical truth / reconciliation)
```

The replay engine injects noise on purpose: duplicate deliveries, late arrivals, official corrections. The Flink job emits the stream faithfully and filters nothing. Exact redeliveries collapse idempotently on read; late arrivals are preserved, because they are the divergence the product exists to surface.

The signal core is shared. `signals/matchup_core.py` holds the computation both paths call -- the batch dbt model and the Flink UDF -- so the two cannot drift. That is the anti-drift guarantee behind the reconciliation being meaningful at all.

## Stack

- **Event bus:** Redpanda (Kafka API) with Confluent Schema Registry for Avro contracts
- **Stream processing:** PyFlink 2.2.0 on Flink 1.20.3
- **Lakehouse:** Apache Iceberg on MinIO, via a REST catalog and PyIceberg
- **Batch transforms:** dbt-duckdb (SQL, incremental, and Python models)
- **Dashboard:** Streamlit + Plotly
- **Observability:** Prometheus + Grafana
- **Language:** Python 3.11; ruff for lint and format, enforced by pre-commit

## Tests and CI

258 unit tests and 123 dbt tests, all passing. CI runs `ruff check`, `ruff format --check`, and the unit suite with coverage on every push. The dbt tests run locally against the materialized lakehouse.

The unit suite includes anti-drift contracts: the calibrated magnitude map is pinned row by row against the seed CSV that the same generator run produced, so the runtime signal and its audit trail cannot diverge silently.

## Architecture Decision Records

The load-bearing decisions live in `docs/adr/`. Each names the alternatives rejected and the consequences accepted. A few worth reading first:

| ADR | Title |
|---|---|
| 0001 | Why a dual-path architecture |
| 0013 | BATTER_UNCERTAIN state representation (categorical, not sentinel) |
| 0015 | Projected batter source during the uncertainty window |
| 0020 | Resolution via dbt double emission |
| 0021 | Streaming migration: making the dual path comparable |
| 0026 | Dashboard reconciliation: scope, signals, and method |
| 0027 | Calibrated matchup magnitudes (delta method, full season) |
| 0028 | An irresolvable matchup is null, not zero |

ADR 0027 is worth a look for a method that was measured and rejected with evidence: the per-bucket league aggregate produced an inverted left-handed split, because platooning managers select who faces whom, so bucket aggregates measure roster usage rather than the matchup effect. The delta method removes that bias, and the ADR shows both numbers.

ADR 0028 documents a defect and its correction: a lookup default fabricated a `0.0` for a matchup that could not be computed, and that fabricated zero reached the classifier as a spurious divergence. The fix records `NULL` instead -- "could not compute" is the absence of a value, not a neutral one -- and the ADR states what the data showed, including where its own first draft was wrong.

## Running locally

Requires Docker, Python 3.11, and roughly 4 GB of free disk for the local lakehouse.

```bash
# 1. Bring up the local stack: Redpanda, MinIO, Iceberg REST catalog,
#    Flink, Prometheus, Grafana.
docker compose -f infra/docker/docker-compose.yml up -d

# 2. Install dependencies. Two environments: streaming/dashboard, and batch.
python3.11 -m venv .venv && .venv/bin/pip install -e ".[dev]"
python3.11 -m venv .venv-batch && .venv-batch/bin/pip install -r requirements-batch.txt
.venv/bin/pre-commit install

# 3. Replay a day of games into Kafka, with noise and lineup uncertainty.
.venv/bin/python -m ingestion.replay_engine.run \
    --game-date 2024-04-02 --speed 2000 --limit 1500 \
    --uncertainty-rate 1.0 --seed 42 \
    --lineup-cache-path data/precomputed/lineups.json

# 4. Submit the streaming matchup job.
bash streaming/flink_jobs/matchup/submit.sh

# 5. Bridge Iceberg into DuckDB and build the models.
.venv-batch/bin/python infra/scripts/refresh_iceberg_sources.py
.venv-batch/bin/python infra/scripts/materialize_dbt_sources.py \
    --namespace streaming --table matchup_signals \
    --metadata-location "<from dbt/.iceberg_sources.json>"
cd dbt && ../.venv-batch/bin/dbt build --profiles-dir .

# 6. Open the dashboard.
.venv/bin/streamlit run apps/dashboard/main.py
```

Unit tests: `.venv/bin/python -m pytest tests/unit/ --no-cov -q`

## What this project is not

- Not an outcome predictor and not a betting system.
- Not a tutorial. It is a system with real engineering decisions and their costs.
- It does not fabricate data. Where there is no source -- team names, venue, jersey numbers, earned runs -- the dashboard shows the gap rather than inventing a value. Earned runs, for instance, are not derivable without fielding-error data, so runs are shown instead and the omission is stated.

## Known limitations

Documented rather than hidden:

- The projected batter that drives a reduced-confidence emission is not persisted on the output row, so a `NULL` signal value cannot be explained from the row alone (ADR 0028). Persisting it is the next contract change.
- `confirmed_late` is unreachable for the matchup signal today: the late-arrival flag is not threaded into the long signal-values model.
- Leverage and fatigue have no streaming twin yet; per ADR 0026 D4 they are deterministic from the pitch's own inputs, so their streaming and canonical reads are the same computation.
- The dashboard reads a fixed `game_pk`; a game selector is not built.

## Project context

Bullpen Signal is built in public as a portfolio piece. The thesis above is the load-bearing claim. Everything else is the system that defends it.

Author: Ivan F. Gruber
