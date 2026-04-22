# Commit plan

A suggested sequence for landing this repo as a series of real commits
rather than one giant initial drop. Each item is one commit; most are
under 30 minutes of adjust-and-push work.

Make it your own — renaming, reordering, dropping items, merging items,
adding items. Anything except squashing to a single commit.

## Phase 0 — scaffolding

1. **chore: repo scaffolding** — README, LICENSE, `.gitignore`, `pyproject.toml`, `Makefile`, `.env.example`, directory skeleton with `.gitkeep` files.
2. **docs: ADRs 1–3** — dual-path, Redpanda, Iceberg.
3. **infra: local docker stack** — `infra/docker/docker-compose.yml`, `prometheus.yml`, its README. Confirm `make up` and `make down` work on your machine before committing.
4. **feat(ingestion): event models and config** — `events.py`, `config.py`, `mapping.py`, `producer.py`. No runner yet.
5. **feat(ingestion): statcast source** — `statcast_source.py` with synthesized event times. Include ADR 0006.
6. **feat(ingestion): statsapi source** — `statsapi_source.py` (graceful-degradation lookups).
7. **feat(ingestion): noise injector** — `ingestion/noise_injector/__init__.py` plus the noise injector unit tests. First commit that adds test coverage.
8. **feat(ingestion): replay runner CLI** — `run.py` wiring everything together. Try a `--dry-run` locally before pushing.
9. **test: mapping unit tests** — adds `test_mapping.py`.
10. **ci: lint and unit tests on push** — `.github/workflows/ci.yml`.
11. **docs: architecture overview** — `docs/architecture/overview.md`, ADRs 4–6.
12. **feat(streaming): Avro schemas** — pitches, game state, corrections, alerts.
13. **feat(streaming): flink job specs** — READMEs in each job directory. Deliberately no code; the spec earns its own commit.
14. **feat(batch): dbt project scaffold** — `dbt_project.yml`, `profiles.example.yml`, staging sources and `stg_pitches.sql`, intermediate window, marts and reconciliation READMEs.
15. **feat(apps): streamlit dashboard placeholder** — `apps/dashboard/main.py` and its README.
16. **docs: case studies template** — `docs/case_studies/README.md` and `_template.md`.

## Phase 1 — first moving parts

Suggested direction, not a strict script:

17. Flink Kafka source wired up; end-to-end pitch count sink for smoke.
18. `fatigue` job first pass — pitch count state only.
19. `fatigue` job v2 — velocity and spin deltas.
20. `leverage` job first pass — broadcast state for the LI lookup.
21. `matchup` job first pass — pitcher pitch-mix state only.
22. `alert_orchestrator` rule-based v1.
23. Dashboard live tab wired to `alerts.v1`.

Each of those is a LinkedIn-sized chunk. Post-worthy individually, stronger
as a sequence.
