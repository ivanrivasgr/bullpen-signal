"""Integration coverage for DuckDB-bronze -> dbt -> silver.pitch_events.

Scope: Local DuckDB bronze.pitches relation -> dbt run silver_pitch_events
       -> silver.silver_pitch_events (DuckDB).

Does NOT test:
- The Flink -> Kafka -> Iceberg bronze path (covered by test_smoke_job.py,
  test_smoke_job_restart.py, test_bronze_pitches_iceberg.py).
- The PyIceberg -> Arrow -> DuckDB materialization path (covered by unit
  test test_materialize_dbt_sources.py).

Why bypass Iceberg here: PyIceberg 0.11.1 write path requires pyarrow >= 17,
which conflicts with apache-beam <17 from PyFlink 2.2.0. The dependency
tension is documented in the commit body and will be resolved as part of the
silver -> Iceberg publish work in a separate commit.

Side effect: this test runs dbt with --full-refresh, which rebuilds
silver_pitch_events from scratch. Any rows produced by prior local runs of
./dbt/run.sh are replaced. Regenerate them with ./dbt/run.sh after running
this test if needed.

Requires: a working dbt-duckdb installation. Does NOT require Iceberg, MinIO,
Flink, or Kafka.
"""

from __future__ import annotations

import os
import subprocess
import time
from datetime import UTC

import duckdb
import pyarrow as pa
import pytest

from infra.scripts.materialize_dbt_sources import default_dbt_duckdb_path
from ingestion.replay_engine.events import PitchEvent
from tests._paths import REPO_ROOT
from tests.integration.test_bronze_pitches_iceberg import _copy_pitch
from tests.integration.test_smoke_job import _build_synthetic_pitches

pytestmark = [pytest.mark.integration, pytest.mark.slow]

# Synthetic provenance fixtures. Bronze normally receives these from
# Flink+Kafka in the production path; this test bypasses that and writes
# directly to DuckDB. The values below satisfy the bronze schema contract
# but do not represent real Kafka coordinates.
SYNTHETIC_KAFKA_PARTITION = 0
SYNTHETIC_SOURCE_OFFSET_BASE = 1_000_000


def _ensure_dbt_profile() -> None:
    profile = REPO_ROOT / "dbt/profiles.yml"
    if not profile.exists():
        profile.write_text((REPO_ROOT / "dbt/profiles.yml.example").read_text())


def _write_pitches_directly_to_duckdb_bronze(pitches: list[PitchEvent]) -> None:
    """Write pitches directly to the local DuckDB bronze table.

    Bypasses both Flink+Kafka (production path) and PyIceberg writes (which
    would require pyarrow >= 17, conflicting with apache-beam <17 from
    PyFlink 2.2.0). The local-dev tension between PyFlink and PyIceberg
    write-path requirements is documented in the commit body and will be
    resolved as part of the silver publish work in a separate commit.
    """
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


def _run_dbt_silver_directly() -> None:
    """Run dbt for silver_pitch_events without the iceberg materialize step.

    Uses --full-refresh to recreate the table from scratch, making the test
    self-contained regardless of the existing MAX(event_time) in silver. The
    silver_pitch_events model is incremental; without --full-refresh, rows
    with event_time < MAX(existing) are filtered out by the model's own
    incremental predicate. Any existing local dev rows in silver_pitch_events
    are replaced; regenerate them with ./dbt/run.sh after the test.

    Bypasses dbt/run.sh because that script calls materialize_dbt_sources.py,
    which would overwrite the bronze rows written directly to DuckDB above.
    """
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


def _silver_rows_for_game(game_pk: int) -> list[tuple[object, ...]]:
    conn = duckdb.connect(str(default_dbt_duckdb_path()))
    try:
        return conn.execute(
            """
            SELECT
                game_pk,
                at_bat_number,
                pitch_number,
                pitcher_id,
                is_late_arrival,
                is_duplicate,
                correction_of,
                ingestion_time IS NOT NULL AS has_ingestion_time,
                kafka_partition IS NOT NULL AS has_kafka_partition,
                source_offset  IS NOT NULL AS has_source_offset
            FROM silver.silver_pitch_events
            WHERE game_pk = ?
            ORDER BY pitch_number
            """,
            [game_pk],
        ).fetchall()
    finally:
        conn.close()


def test_silver_pitch_events_lands_bronze_rows_with_audit_columns() -> None:
    game_pk = int(time.time() * 1000)

    pitches = [
        _copy_pitch(
            pitch,
            game_pk=game_pk,
            at_bat_number=70,
            pitch_number=index + 1,
            pitcher_id=805400 + index,
            batter_id=860270 + index,
            is_late_arrival=index == 1,
            is_duplicate=index == 2,
            correction_of="synthetic-correction" if index == 2 else None,
        )
        for index, pitch in enumerate(_build_synthetic_pitches(3))
    ]

    _write_pitches_directly_to_duckdb_bronze(pitches)
    _run_dbt_silver_directly()

    rows = _silver_rows_for_game(game_pk)
    assert len(rows) == len(pitches)
    assert rows == [
        (game_pk, 70, 1, 805400, False, False, None, True, True, True),
        (game_pk, 70, 2, 805401, True, False, None, True, True, True),
        (game_pk, 70, 3, 805402, False, True, "synthetic-correction", True, True, True),
    ]
