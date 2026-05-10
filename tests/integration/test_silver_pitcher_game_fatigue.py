"""Integration coverage for silver_pitch_events -> dbt -> silver.pitcher_game_fatigue.

Scope: Writes pitches for three pitchers with known counts directly to
       DuckDB bronze.pitches, runs dbt for both silver models, and verifies
       that fatigue_bucket values match ADR 0008 thresholds.

Does NOT test:
- The Flink -> Kafka -> Iceberg bronze path.
- The PyIceberg -> Arrow -> DuckDB materialization path.

Side effect: this test runs dbt with --full-refresh for both silver models,
replacing any existing local dev rows. Regenerate them with ./dbt/run.sh
after running this test if needed.

Requires: a working dbt installation in PATH. Does NOT require Iceberg, MinIO,
Flink, or Kafka (though the conftest autouse fixture skips if the stack is
unreachable).
"""

from __future__ import annotations

import os
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pyarrow as pa
import pytest

from infra.scripts.materialize_dbt_sources import default_dbt_duckdb_path
from ingestion.replay_engine.events import PitchEvent
from tests.integration.test_bronze_pitches_iceberg import _copy_pitch
from tests.integration.test_smoke_job import _build_synthetic_pitches

pytestmark = [pytest.mark.integration, pytest.mark.slow]

SYNTHETIC_KAFKA_PARTITION = 0
SYNTHETIC_SOURCE_OFFSET_BASE = 2_000_000


def _ensure_dbt_profile() -> None:
    profile = Path("dbt/profiles.yml")
    if not profile.exists():
        profile.write_text(Path("dbt/profiles.yml.example").read_text())


def _write_pitches_to_duckdb_bronze(pitches: list[PitchEvent]) -> None:
    db_path = default_dbt_duckdb_path()
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute("CREATE SCHEMA IF NOT EXISTS bronze")
        rows = []
        for index, pitch in enumerate(pitches):
            d = pitch.model_dump()
            ingestion_time = d.pop("ingest_time")
            if ingestion_time.tzinfo is None:
                ingestion_time = ingestion_time.replace(tzinfo=UTC)
            d["ingestion_time"] = ingestion_time
            d["kafka_partition"] = SYNTHETIC_KAFKA_PARTITION
            d["source_offset"] = SYNTHETIC_SOURCE_OFFSET_BASE + index
            rows.append(d)
        arrow_table = pa.Table.from_pylist(rows)
        existing = conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema='bronze' AND table_name='pitches'"
        ).fetchone()[0]
        conn.register("_new_rows", arrow_table)
        if existing == 0:
            conn.execute("CREATE TABLE bronze.pitches AS SELECT * FROM _new_rows")
        else:
            conn.execute("INSERT INTO bronze.pitches SELECT * FROM _new_rows")
    finally:
        conn.close()


def _run_dbt_silver_full_refresh() -> None:
    _ensure_dbt_profile()
    env = os.environ.copy()
    env["DBT_SEND_ANONYMOUS_USAGE_STATS"] = "False"
    result = subprocess.run(
        [
            "dbt",
            "run",
            "--profiles-dir",
            ".",
            "--select",
            "silver_pitch_events",
            "silver_pitcher_game_fatigue",
            "--full-refresh",
        ],
        cwd="dbt",
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise AssertionError(f"dbt run failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")


def _fatigue_rows_for_game(game_pk: int) -> dict[int, tuple[int, str]]:
    """Return {pitcher_id: (pitch_count, fatigue_bucket)} for a game."""
    conn = duckdb.connect(str(default_dbt_duckdb_path()))
    try:
        rows = conn.execute(
            """
            SELECT pitcher_id, pitch_count, fatigue_bucket
            FROM silver.silver_pitcher_game_fatigue
            WHERE game_pk = ?
            ORDER BY pitcher_id
            """,
            [game_pk],
        ).fetchall()
    finally:
        conn.close()
    return {row[0]: (row[1], row[2]) for row in rows}


def _build_pitcher_pitches(
    *,
    game_pk: int,
    pitcher_id: int,
    batter_id: int,
    count: int,
    at_bat_number: int,
    base_offset: int,
    base_time: datetime,
) -> list[PitchEvent]:
    # _build_synthetic_pitches uses second=i*10, so it only supports up to 5
    # pitches (0,10,20,30,40 are valid seconds; 60 is not). Use a small pool
    # and cycle through it with modulo for larger counts.
    pool = _build_synthetic_pitches(5)
    return [
        _copy_pitch(
            pool[i % len(pool)],
            game_pk=game_pk,
            at_bat_number=at_bat_number,
            pitch_number=i + 1,
            pitcher_id=pitcher_id,
            batter_id=batter_id,
            is_late_arrival=False,
            is_duplicate=False,
            correction_of=None,
            event_time=base_time + timedelta(seconds=i),
            ingest_time=base_time + timedelta(seconds=i),
        )
        for i in range(count)
    ]


def test_fatigue_bucket_thresholds_match_adr_0008() -> None:
    game_pk = int(time.time() * 1000)
    base_time = datetime.now(UTC)

    low_pitcher_id = 900001
    medium_pitcher_id = 900002
    high_pitcher_id = 900003

    pitches: list[PitchEvent] = []
    pitches += _build_pitcher_pitches(
        game_pk=game_pk,
        pitcher_id=low_pitcher_id,
        batter_id=800001,
        count=10,
        at_bat_number=1,
        base_offset=0,
        base_time=base_time,
    )
    pitches += _build_pitcher_pitches(
        game_pk=game_pk,
        pitcher_id=medium_pitcher_id,
        batter_id=800002,
        count=35,
        at_bat_number=2,
        base_offset=100,
        base_time=base_time + timedelta(minutes=5),
    )
    pitches += _build_pitcher_pitches(
        game_pk=game_pk,
        pitcher_id=high_pitcher_id,
        batter_id=800003,
        count=75,
        at_bat_number=3,
        base_offset=200,
        base_time=base_time + timedelta(minutes=15),
    )

    _write_pitches_to_duckdb_bronze(pitches)
    _run_dbt_silver_full_refresh()

    results = _fatigue_rows_for_game(game_pk)

    assert len(results) == 3, f"Expected 3 pitchers, got {len(results)}: {results}"
    assert results[low_pitcher_id] == (10, "low"), results[low_pitcher_id]
    assert results[medium_pitcher_id] == (35, "medium"), results[medium_pitcher_id]
    assert results[high_pitcher_id] == (75, "high"), results[high_pitcher_id]


def test_fatigue_model_excludes_duplicate_pitches_from_count() -> None:
    game_pk = int(time.time() * 1000) + 1
    base_time = datetime.now(UTC)
    pitcher_id = 900010
    base_pitches = _build_synthetic_pitches(5)

    # 5 real + 3 duplicates -> pitch_count should be 5 (duplicates excluded)
    pitches = [
        _copy_pitch(
            base_pitches[i % len(base_pitches)],
            game_pk=game_pk,
            at_bat_number=10,
            pitch_number=i + 1,
            pitcher_id=pitcher_id,
            batter_id=800010,
            is_duplicate=(i >= 5),
            is_late_arrival=False,
            correction_of=None,
            event_time=base_time + timedelta(seconds=i),
            ingest_time=base_time + timedelta(seconds=i),
        )
        for i in range(8)
    ]

    _write_pitches_to_duckdb_bronze(pitches)
    _run_dbt_silver_full_refresh()

    results = _fatigue_rows_for_game(game_pk)
    assert pitcher_id in results, f"Pitcher {pitcher_id} not found in {results}"
    pitch_count, bucket = results[pitcher_id]
    assert pitch_count == 5, f"Expected 5 non-duplicate pitches, got {pitch_count}"
    assert bucket == "low", f"Expected 'low' bucket for 5 pitches, got '{bucket}'"
