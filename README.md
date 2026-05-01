# Bullpen Signal

A dual-path decision engine for pitcher fatigue, bullpen readiness, and matchup leverage.

What real-time gets you first, what batch gets you right, and why a manager needs both in the dugout.

## Status

Phase 1 in progress. Bronze lakehouse layer is live: a Flink streaming job reads Avro pitch events from Kafka and writes them to an Iceberg `bronze.pitches` table on MinIO, queryable from DuckDB. Streaming jobs for fatigue / leverage / matchup signals, alert orchestrator, silver / gold layers, and the dashboard are not yet implemented.

## The thesis

In baseball, three decisions are made in the same 30-second window between pitches: pull the pitcher, warm the bullpen, change for matchup. A real-time system gives you signals in seconds but with incomplete information (provisional pitch classification, preliminary spin rate, leverage index without the next confirmed batter). A batch system gives you canonical truth but arrives too late for the operational decision.

Bullpen Signal runs both paths over the same ground truth, a deterministic replay of real MLB games, and measures with hard metrics where each architecture wins and loses. It is not streaming vs batch. It is when each is the right answer, and how a reconciliation layer turns that tension into a product.

## Architecture

Replay engine publishes Statcast pitch-level data and MLB StatsAPI game state to Kafka. Two paths consume the same stream:

- Streaming: Flink stateful jobs compute fatigue score, leverage index, and matchup edge in real time, feeding an alert orchestrator.
- Batch: dbt incremental models reconstruct the canonical truth over Iceberg, applying late arrivals and official corrections.

Both land in an Iceberg lakehouse following a medallion pattern. A reconciliation mart compares every streaming alert against the canonical truth and records the delta. The dashboard surfaces three views: live dugout, canonical truth, and reconciliation.

See `docs/architecture/` for diagrams and `docs/adr/` for key decisions.

## Stack

- Ingestion: pybaseball (Statcast), MLB StatsAPI, custom replay engine
- Event bus: Redpanda (local), Confluent Cloud (demo deploy)
- Streaming: Apache Flink with event time, windowing, exactly-once
- Lakehouse: Apache Iceberg on MinIO (local) or S3 (cloud)
- Batch: dbt core with incremental materializations
- Quality: Great Expectations
- Lineage: OpenLineage
- Observability: Prometheus + Grafana
- Serving: Streamlit
- Infra: Docker Compose (local), Terraform (cloud)

## Three signals

Each signal has a streaming version (fast, provisional) and a batch version (slow, canonical). The reconciliation layer measures the delta.

- **Fatigue score**: weighted combination of pitch count, velocity delta vs early-game baseline, spin rate delta vs season baseline, pace between pitches, and command drop (zone percent, edge percent). Calibrated against observed pitcher removals where the removal was performance-driven.
- **Leverage index**: standard Tango-style LI by game state, updated on every count, base, or score change. Streaming is provisional because the next batter is not always confirmed yet.
- **Matchup edge**: expected wOBA of the active pitcher vs the next confirmed batter using pitch mix splits by handedness and whiff rate.

## Getting started

Requires Docker, Docker Compose, and Python 3.11 or later.

```bash
make up          # bring up Redpanda, MinIO, Flink, Iceberg REST catalog
make replay      # run the replay engine against a sample game
make dashboard   # launch the Streamlit dashboard
make down        # tear everything down
```

See `infra/docker/README.md` for what each service does and why.

## Roadmap

- **Phase 0** — scaffolding, replay engine, local infra up
- **Phase 1** — Flink jobs for fatigue, leverage, matchup, alert orchestrator, live dashboard
- **Phase 2** — medallion in Iceberg, dbt incremental, quality checks
- **Phase 3** — reconciliation mart, delta dashboard, first case studies
- **Phase 4** — OpenLineage end to end, Grafana SLAs, Terraform cloud deploy
- **Phase 5** — benchmarks, Medium article, portfolio update

## KPIs

These are the numbers the project is built to produce, not add later:

- p50, p95, p99 latency per signal type
- Time-to-first-signal vs time-to-canonical-truth per game
- Correction rate: percent of streaming alerts changed after batch
- Delta magnitude distribution when corrections occur
- Decisions preserved vs reversed for action-level alerts
- Cost per million events, streaming vs batch
- Backfill recovery time for schema changes or bug fixes
- Incidents caught by Great Expectations before hitting production

## Non-goals

- Predicting game outcomes. This is a decision-support system, not a model for win probability at scale.
- Replacing batch with streaming. The project exists to show the boundary between them.
- A generic streaming demo. The domain, the signals, and the reconciliation layer are load-bearing.

## License

MIT. See LICENSE.
