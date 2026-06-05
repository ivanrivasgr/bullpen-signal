# Phase 2 Milestone 2 — Closeout

- **Status:** Closed
- **Window:** 2026-06-01 through 2026-06-05
- **Plan reference:** `docs/phase2/milestone_2_plan.md`
- **Backing ADR:** `docs/adr/0016-matchup-signal-design.md`

## What this milestone delivered

The matchup signal is now materialized end-to-end on local Statcast data. A pitch arriving at `bronze.pitches` is enriched through `silver_pitch_events` → `silver_matchup_events` → `silver_matchup_signals`, picking up the pitcher's fatigue context, the handedness matchup, and finally a per-pitch `signal_value` paired with a `confidence_band` mapped from `lineup_state` per ADR 0016.

The signal generation logic lives in one place — `signals/matchup_signal.py` — as a pure function. The dbt Python model `silver_matchup_signals` imports that function and applies it row-by-row to the matchup events. Phase 3 reconciliation reads this table as the canonical record of what the system would have emitted.

Eight commits landed in five days:
c8bafad feat(phase2): add MatchupRevisionEvent schema and publisher integration
2a526a8 docs(adr): record revision taxonomy for matchup signal updates
c36c59d feat(phase2): materialize matchup signals end-to-end via dbt python model
8d019b4 feat(phase2): add matchup signal generation with confidence band
f9db898 test(phase2): add accepted_values guards on silver_matchup_events handedness
4272865 feat(phase2): wire handedness joins into silver_matchup_events
0f04dd4 feat(phase2): add player_handedness seed extracted from statcast parquets
bbeaa62 feat(phase2): add silver_matchup_events with fatigue join

The first six implement the matchup signal end-to-end. The last two open Milestone 3 — ADR 0017 formalizes the revision taxonomy and the Avro schema + Python contract for `MatchupRevisionEvent` lands on the publisher.

## What the plan did not anticipate

The plan from 2026-05-30 outlined four bullet points: silver_matchup_events with the fatigue join, handedness wiring, signal generation function, integration into silver. Three things surfaced during implementation that the plan did not predict.

### Schema migration had not propagated end-to-end

ADR 0013 added `lineup_state` to `bronze.pitches` on 2026-05-28 (commit 77568b7). The migration was correct in code — the Iceberg schema definition, the Avro schema, the Pydantic event, and the converter all gained the column. What had not happened was the propagation through the rest of the data path: `silver_pitch_events.sql` did not select `lineup_state` from bronze, the local DuckDB materialization of bronze did not have the column, and the local Iceberg snapshot was created before the migration.

This only became visible on Wednesday afternoon when the dbt Python model tried to materialize `silver_matchup_signals` and failed with `KeyError: 'lineup_state'` because the matchup events row coming into the signal function did not carry the field.

The fix took several hours and revealed the full extent of the gap. Iceberg `bronze.pitches` was dropped and recreated with the current schema (31 fields, including `lineup_state` as field_id=31). The smoke Flink job in `streaming/flink_jobs/_smoke/job.py` had to be patched in three places — the Kafka source DDL, the bronze insert SQL (with `lineup_state` placed last to match the Iceberg table's column order), and the event_time / ingestion_time casts to `TIMESTAMP_LTZ(6)` to match the sink precision. The Iceberg connector validated cleanly only after all three were aligned.

`silver_pitch_events.sql` and `silver_matchup_events.sql` were updated to carry `lineup_state` through the silver layer. After a full-refresh of the silver chain against a clean bronze snapshot, the materialization succeeded end-to-end: 200 pitches in bronze, 200 matchup signals in silver, all `confidence_band = full` because the replay ran without the BATTER_UNCERTAIN window enabled.

### Switch-hitters

The first version of `dbt/seeds/player_handedness.csv` was extracted by SELECT DISTINCT on `(pitcher, p_throws)` and `(batter, stand)` from the Statcast 2024 parquets. The DISTINCT collapsed accidentally-duplicated rows, but it did not collapse a more fundamental case: **switch-hitters bat from both sides of the plate**, so the same player_id legitimately appears with `stand = 'L'` in some at-bats and `stand = 'R'` in others. The first seed had 1,266 rows with 20 batters duplicated.

The handedness join in `silver_matchup_events` produced 8 duplicate rows downstream when an Ohtani-class player batted, because the LEFT JOIN matched the same pitch against both handedness rows. The natural-key uniqueness test caught the duplicates.

The fix was not to pick one side arbitrarily. Switch-hitters are real, they exist by name in this dataset (51 batters in the April + September 2024 windows), and they need to be represented honestly. The seed schema was extended: `hand` now accepts `'L'`, `'R'`, or `'S'`. The `handedness_matchup` column gains five new valid values: `R_vs_S`, `L_vs_S`, `S_vs_R`, `S_vs_L`, `S_vs_S`. The `accepted_values` dbt tests were extended accordingly, and `signals/matchup_signal.py` got five new placeholder signal values for the S-side matchups.

The reasoning for the placeholder magnitudes is documented in the module: a switch-hitter facing a same-handed pitcher gets the favorable opposite-side matchup, so `R_vs_S` and `L_vs_S` use the same magnitude as the natural opposite-side matchups (-0.10). The placeholder values stay placeholders; Phase 3 calibrates them against realized outcomes.

### Flink connector behavior

The smoke job submitted cleanly only after the column-order fix above, but two other Flink-side surprises showed up. First, when the Iceberg connector was recreated with `--recreate`, the s3fs library used to delete the underlying MinIO data failed with `MissingContentMD5` — a known incompatibility between s3fs and recent MinIO releases. The workaround was to delete the files using `mc rm` through the MinIO container itself, then call `ensure_bronze_pitches_table` to recreate the table from the up-to-date schema.

Second, when the Flink smoke job was restarted against the existing topic, `scan.startup.mode = 'earliest-offset'` caused it to re-read everything in the topic, including the previous replay's noise-injected duplicates. The topic was wiped and recreated before the clean replay was run, which was the first end-to-end clean materialization.

Neither surprise is a defect in the design. Both are local-development realities that the production streaming path (scheduled for 2026-06-20 per ADR 0016) will not have because Flink in production reads from a managed catalog that the dev stack approximates imperfectly.

## What was deferred to Milestone 3

- The revision producer. ADR 0017 and the wire contract for `MatchupRevisionEvent` are in place (commits `2a526a8`, `c8bafad`), but the producer that emits revisions when lineups confirm or corrections arrive is Milestone 3 work.
- The reconciliation ledger in `dbt/models/marts/`. The marts directory still does not contain models. The should-have-fired ledger Chad named on 2026-05-19 lands in Milestone 3 / Phase 3.
- The migration of matchup signal computation from dbt batch to a Flink streaming job. ADR 0016 scheduled this for 2026-06-20.
- The integration test that verifies end-to-end: replay → Kafka → Flink → Iceberg → DuckDB → dbt silver chain → silver_matchup_signals with the expected row count. The manual run on Wednesday verified the path; the automated integration test follows.

## Status of decisions left honest

These are stubs and placeholders deliberately left visible rather than masked:

- `_infer_batting_team_id` in `ingestion/replay_engine/uncertainty_window.py` returns `None`. Statcast pitch rows do not carry batting_team_id and the replay engine does not yet thread it through. The BATTER_UNCERTAIN tagging works correctly without it; only the projected-batter substitution is dropped inside the uncertainty window. A follow-up commit threads team identity through.
- `_approximate_lineup_position` uses `(at_bat_number - 1) % 9 + 1`. Breaks down after pinch hitters and double-switches. Acceptable for early-game uncertainty windows where lineup position is most stable.
- The IL exception filter from ADR 0015 remains documented and deferred. StatsAPI does not expose historical IL status in a form the precompute step can consume reliably.
- The signal_value table in `signals/matchup_signal.py` carries placeholder magnitudes. ADR 0008's precedent of declared-arbitrary thresholds is honored. Phase 3 calibrates against realized outcomes.

## Definition of done — verified

The plan's three definition-of-done bullets:

- silver_matchup_events materializes from silver_pitch_events. **Done.** Verified on 200 rows from the 2026-04-15 replay.
- confidence_band reflects lineup_state per ADR 0016. **Done.** dbt accepted_values test guards the contract at build time.
- Phase 3 has enough state on the matchup_events / matchup_signals tables to evaluate reconciliation against canonical outcomes. **Done.** `silver_matchup_signals` carries `signal_value`, `confidence_band`, and `lineup_state_at_emission`; the natural key is preserved for joins against any canonical-outcomes mart Phase 3 builds.

dbt build silver --full-refresh: PASS=49, ERROR=0.
Full unit suite: 151 of 151 passing.

## What this closes and what it opens

This closes Phase 2 Milestone 2. The matchup signal exists end-to-end, is deterministically computable on historical data, and emits with a confidence band that downstream consumers can act on.

It opens Milestone 3, where the revision producer and the should-have-fired ledger turn the static signal into a live system that can revise its own emissions and report retrospectively on what it would have done.
