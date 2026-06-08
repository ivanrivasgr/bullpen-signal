# Bullpen Signal

A dual-path decision engine for pitcher fatigue, bullpen readiness, and matchup leverage. What real-time gets you first, what batch gets you right, and why a manager needs both in the dugout.

## The thesis

In baseball, three decisions are made in the same 30-second window between pitches: pull the pitcher, warm the bullpen, change for matchup. A real-time system gives you signals in seconds but with incomplete information — provisional pitch classification, preliminary spin rate, the next batter not yet confirmed. A batch system gives you canonical truth but arrives too late for the operational decision.

Bullpen Signal runs both paths over the same ground truth — a deterministic replay of real MLB games — and measures with hard metrics where each architecture wins and loses. It is not streaming versus batch. It is *when* each is the right answer, and how a reconciliation layer turns that tension into a product.

## Status

Phase 2 Milestone 2 closed 2026-06-05. The matchup signal materializes end-to-end on real Statcast 2024 data through the silver and marts layers. Phase 3 reconciliation triangle (canonical outcomes, should-have-fired ledger, summary aggregation) is in place. Revision taxonomy and the revision event wire contract land per ADR 0017.

| Layer | Status |
|---|---|
| Replay engine (Statcast → Kafka, Avro, Schema Registry) | ✅ |
| Bronze Iceberg on MinIO via PyIceberg | ✅ |
| Silver dbt models (pitch events, fatigue, matchup signals) | ✅ |
| Marts (canonical outcomes, should-have-fired ledger, reconciliation summary) | ✅ |
| Revision event contract + emitter (function pure) | ✅ |
| Revision producer (batch + streaming) | Phase 3 |
| Streaming Flink job for matchup signal | Scheduled 2026-06-20 (ADR 0016) |
| Alert orchestration + dashboard live data | Phase 4 |
| Cloud deployment + CI/CD + observability | Phase 4 |

169 unit tests passing. `dbt build` clean across silver and marts. Honest stubs documented inline rather than hidden — see `docs/phase2/milestone_2_closeout.md`.

## Architecture

The replay engine publishes Statcast pitch-level data and MLB StatsAPI game state to Kafka topics. Two paths consume the same stream:

- **Streaming** (Phase 3+): Flink stateful jobs compute fatigue, leverage, and matchup signals in real time, emitting to topics that an alert orchestrator subscribes to.
- **Batch** (today): dbt incremental and Python models on DuckDB reconstruct canonical truth over Iceberg snapshots, applying late arrivals, duplicates, and official corrections.

Both paths land in a medallion lakehouse on Iceberg. A reconciliation layer compares every streaming emission against canonical truth and records the delta. The dashboard surfaces three views: live dugout, canonical truth, and reconciliation.
Statcast parquets   StatsAPI lineups
│                  │
└────────┬─────────┘
│
replay engine (Avro)
│
┌───────┴───────┐
│               │
Kafka          (uncertainty window injection)
│
┌─────┴─────┐
│           │
Flink     Iceberg (bronze)
(Phase 3)     │
│
dbt silver
(pitch events, fatigue, matchup events, matchup signals)
│
marts
(canonical outcomes, should-have-fired ledger,
reconciliation summary)
│
Dashboard

See `docs/architecture/` for component diagrams and `docs/adr/` for the decisions behind each choice.

## Stack

- **Event bus:** Redpanda (Kafka API) with Confluent Schema Registry for Avro contracts
- **Stream processing:** PyFlink (Phase 3 streaming jobs)
- **Lakehouse:** Apache Iceberg on MinIO via PyIceberg
- **Local query / batch transforms:** DuckDB + dbt-duckdb (incremental + Python models)
- **Data sources:** Statcast (via pybaseball) and MLB StatsAPI
- **Observability:** Prometheus + Grafana (containers running; instrumentation in Phase 4)
- **Languages:** Python 3.11, SQL, a thin layer of Flink SQL DDL

## Architecture Decisions (ADRs)

The repo's load-bearing decisions live as ADRs. Each one names the alternatives rejected and the consequences accepted.

| ADR | Title | Status |
|---|---|---|
| 0001 | Why dual-path | Accepted |
| 0002 | Redpanda for event bus | Accepted |
| 0003 | Iceberg on MinIO | Accepted |
| 0004 | PyFlink over Java | Accepted |
| 0005 | DuckDB as Phase 0 target | Accepted |
| 0006 | Synthesized event times for replay | Accepted |
| 0007 | ML provenance and reproducibility | Accepted |
| 0008 | Silver design decisions | Accepted |
| 0009 | dbt on DuckDB as local engine | Accepted |
| 0012 | Streaming foundation decisions | Accepted |
| 0013 | BATTER_UNCERTAIN state representation (categorical, not probabilistic) | Accepted |
| 0014 | Uncertainty window injection mechanism | Accepted |
| 0015 | Projected batter source during uncertainty | Accepted |
| 0016 | Matchup signal design — batch first, streaming in Phase 3 | Accepted |
| 0017 | Revision taxonomy for matchup signal updates | Accepted |
| 0018 | `would_have_been_correct` as heuristic, not metric | Accepted |

## Running locally

The repo expects Docker, Python 3.11, and roughly 4 GB free disk for the local lakehouse.

### One-time setup

```bash
# Spin up the local stack: Redpanda, MinIO, Schema Registry,
# Iceberg REST catalog, Flink, Prometheus, Grafana.
docker compose -f infra/docker/docker-compose.yml up -d

# Install Python dependencies in a venv.
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Install pre-commit hooks (ruff, yaml checks, trailing whitespace).
pre-commit install

# Create the Iceberg bronze.pitches table.
python -m infra.scripts.create_bronze_tables
```

### Running a replay

```bash
# Submit the Flink smoke job that reads pitches.raw and writes to bronze.pitches.
docker cp streaming/flink_jobs/_smoke/job.py bullpen-flink-jm:/tmp/smoke_job_run.py
docker exec bullpen-flink-jm /opt/flink/bin/flink run -py /tmp/smoke_job_run.py --detached

# Run a deterministic replay of one day of MLB games.
python -m ingestion.replay_engine.run --game-date 2024-04-15 --speed 1000 --limit 200
```

### Materializing the lakehouse

```bash
# Refresh dbt's view of the Iceberg metadata.
python -m infra.scripts.refresh_iceberg_sources

# Materialize bronze.pitches into DuckDB for dbt.
python -m infra.scripts.materialize_dbt_sources \
    --metadata-location "$(python -c 'import json; print(json.load(open(\"dbt/.iceberg_sources.json\"))[\"bronze.pitches\"][\"metadata_location\"])')"

# Build the silver chain and marts.
cd dbt && dbt build --select silver marts
```

### Running tests

```bash
# Unit suite (currently 169 tests).
pytest tests/unit/ --no-cov -q

# dbt tests are included in `dbt build`.
```

## Repository structure
bullpen-signal/
├── apps/
│   └── dashboard/             Streamlit dashboard (live data in Phase 4)
├── data/
│   └── raw/                   Statcast parquets (not in git; pulled via pybaseball)
├── dbt/
│   ├── models/
│   │   ├── silver/            pitch events, fatigue, matchup events + signals
│   │   └── marts/             canonical outcomes, ledger, reconciliation summary
│   ├── seeds/                 player_handedness (extracted from Statcast)
│   └── tests/                 Custom SQL natural-key uniqueness tests
├── docs/
│   ├── adr/                   Architecture Decision Records (0001-0018)
│   ├── phase2/                Milestone plans + narrative closeouts
│   └── architecture/          Component diagrams
├── infra/
│   ├── docker/                docker-compose stack
│   └── scripts/               Iceberg + DuckDB ops helpers
├── ingestion/
│   └── replay_engine/         Statcast → Kafka, noise injection, uncertainty window
├── lakehouse/
│   └── schemas/               PyIceberg schema definitions
├── signals/                   Pure signal generation + revision emitter
├── streaming/
│   ├── flink_jobs/            PyFlink job sources (smoke job today; real jobs Phase 3)
│   └── schemas/               Avro schemas for each Kafka topic
└── tests/
├── unit/                  Unit tests (169 passing)
└── integration/           Integration scaffold (Phase 3+)

## What is honest about this repo

Three things are deliberately incomplete and named:

- **The matchup signal_value magnitudes are placeholders.** They encode the conventional baseball intuition that opposite-handed matchups favor the batter and same-handed matchups slightly favor the pitcher, but they are not calibrated against historical outcomes. ADR 0016 documents this; Phase 3 reconciliation will calibrate.
- **`would_have_been_correct` in the should-have-fired ledger is a heuristic.** Sign-only classification against the realized outcome. ADR 0018 documents the limitations explicitly. When Phase 3 accumulates enough outcome data, the column name stays stable and the definition becomes calibrated.
- **The streaming path for the matchup signal is not the matchup writer today.** The smoke Flink job writes pitches to bronze; the matchup signal is materialized via dbt Python on a clean snapshot. ADR 0016 schedules the streaming migration for 2026-06-20.

What you will not find in this repo: stubs disguised as features, placeholders masked as calibrated metrics, or `TODO` comments hiding decisions that should have been ADRs.

## Project context

Bullpen Signal is built in public as a portfolio piece. Development log and architectural decisions are tracked in `docs/adr/` and `docs/phase*/`. The thesis above is the load-bearing claim. Everything else is the system that defends it.
