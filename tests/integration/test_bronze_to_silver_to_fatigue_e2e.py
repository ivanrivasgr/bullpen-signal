"""End-to-end integration coverage for the full bronze -> silver -> Iceberg publish pipeline.

Scope: Appends 120 synthetic pitches for three pitchers to Iceberg bronze.pitches,
       runs the complete ./dbt/run.sh wrapper (refresh_iceberg_sources +
       materialize_dbt_sources + dbt run --full-refresh + publish_dbt_silver),
       and verifies both the resulting DuckDB silver tables and the Iceberg
       silver snapshots.

This is the only integration test that exercises the full run.sh wrapper.
All other silver integration tests bypass the wrapper and call dbt run directly,
which skips the Iceberg materialization step and the Iceberg publish step.

Does NOT test:
- The Flink -> Kafka -> Iceberg bronze path (covered by test_smoke_job.py,
  test_bronze_pitches_iceberg.py).
- Individual silver model SQL contracts (covered by unit tests).
- Individual dbt model runs without the wrapper (covered by
  test_silver_pitch_events.py, test_silver_pitcher_game_fatigue.py).

Side effects:
- Appends 120 rows to Iceberg bronze.pitches (tagged with the test game_pk).
  The rows persist across test runs; each run adds 120 more tagged rows.
- Rebuilds DuckDB silver tables from scratch (--full-refresh). Any local dev
  rows written by a prior ./dbt/run.sh invocation are replaced.
- Appends to Iceberg silver.pitch_events and silver.pitcher_game_fatigue.

Why write to Iceberg bronze instead of DuckDB bronze directly:
  run.sh calls materialize_dbt_sources.py, which reads bronze.pitches from
  Iceberg and overwrites the local DuckDB bronze table. Writing directly to
  DuckDB bronze (as other integration tests do) would lose the injected rows.
  This test must inject into Iceberg bronze so the data survives the
  materialization step.

Why subprocess to .venv-batch for the Iceberg bronze write:
  PyIceberg 0.11.1 write path requires pyarrow>=17. The integration test
  runner uses .venv, which pins pyarrow<17 for apache-beam compatibility.
  The helper serializes the Arrow table to a temp parquet file and delegates
  the Iceberg append to a .venv-batch/bin/python subprocess.

Requires: full local stack (Iceberg REST catalog, MinIO, Redpanda). The
conftest autouse fixture skips this test if Redpanda is unreachable.

Note: this test does NOT run in the default CI job. It is available for local
verification when the full Docker stack is up. The CI gap is documented in
the Milestone 2 closeout.
"""

from __future__ import annotations

import subprocess
import tempfile
import textwrap
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from infra.scripts.create_bronze_tables import load_local_iceberg_catalog
from infra.scripts.materialize_dbt_sources import default_dbt_duckdb_path
from ingestion.replay_engine.events import PitchEvent
from tests.integration.test_bronze_pitches_iceberg import _copy_pitch
from tests.integration.test_smoke_job import _build_synthetic_pitches

pytestmark = [pytest.mark.integration, pytest.mark.slow]

E2E_KAFKA_PARTITION = 0
E2E_SOURCE_OFFSET_BASE = 3_000_000


# ── helpers ───────────────────────────────────────────────────────────────────


def _build_pitcher_pitches(
    *,
    game_pk: int,
    pitcher_id: int,
    batter_id: int,
    count: int,
    at_bat_number: int,
    base_time: datetime,
) -> list[PitchEvent]:
    # _build_synthetic_pitches uses second=i*10, valid only up to n=5 (seconds
    # 0..40). Use a small pool and cycle with modulo for larger counts.
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


def _pitches_to_arrow(pitches: list[PitchEvent], base_offset: int) -> pa.Table:
    rows = []
    for index, pitch in enumerate(pitches):
        d = pitch.model_dump()
        ingest_time = d.pop("ingest_time")
        if ingest_time.tzinfo is None:
            ingest_time = ingest_time.replace(tzinfo=UTC)
        if d["event_time"].tzinfo is None:
            d["event_time"] = d["event_time"].replace(tzinfo=UTC)
        d["ingestion_time"] = ingest_time
        d["kafka_partition"] = E2E_KAFKA_PARTITION
        d["source_offset"] = base_offset + index
        rows.append(d)
    return pa.Table.from_pylist(rows)


def _append_to_iceberg_bronze(pitches: list[PitchEvent], base_offset: int) -> None:
    """Append pitches to Iceberg bronze.pitches via a .venv-batch subprocess.

    Serializes the Arrow table to a temp parquet file, then delegates the
    Iceberg append to .venv-batch/bin/python (which has pyarrow>=17).
    The temp file is always cleaned up even if the subprocess fails.
    """
    arrow = _pitches_to_arrow(pitches, base_offset)

    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
        tmp_path = Path(f.name)

    pq.write_table(arrow, str(tmp_path))

    script = textwrap.dedent(
        f"""
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path('.').resolve()))

        import pyarrow as pa
        import pyarrow.parquet as pq
        from infra.scripts.create_bronze_tables import load_local_iceberg_catalog
        from pyiceberg.io.pyarrow import schema_to_pyarrow

        catalog = load_local_iceberg_catalog()
        iceberg_table = catalog.load_table('bronze.pitches')
        expected = schema_to_pyarrow(iceberg_table.schema())

        arrow = pq.read_table('{tmp_path}')
        cols = []
        for field in expected:
            col = arrow.column(field.name)
            if col.type != field.type:
                col = col.cast(field.type)
            cols.append(col)
        cast = pa.table(
            dict(zip(expected.names, cols, strict=False)),
            schema=expected,
        )
        iceberg_table.append(cast)
        print(f'appended {{cast.num_rows}} rows to bronze.pitches', flush=True)
        """
    )

    try:
        result = subprocess.run(
            [".venv-batch/bin/python", "-c", script],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            raise AssertionError(
                f"Iceberg bronze append failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            )
    finally:
        tmp_path.unlink(missing_ok=True)


def _run_dbt_run_sh_full_refresh() -> None:
    result = subprocess.run(
        ["./dbt/run.sh", "--full-refresh"],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"./dbt/run.sh --full-refresh failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )


def _silver_pitch_event_count_for_game(game_pk: int) -> int:
    conn = duckdb.connect(str(default_dbt_duckdb_path()), read_only=True)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM silver.silver_pitch_events WHERE game_pk = ?",
            [game_pk],
        ).fetchone()[0]
    finally:
        conn.close()


def _silver_fatigue_rows_for_game(game_pk: int) -> dict[int, tuple[int, str]]:
    conn = duckdb.connect(str(default_dbt_duckdb_path()), read_only=True)
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


def _iceberg_snapshot_added_records(identifier: str) -> int:
    catalog = load_local_iceberg_catalog()
    table = catalog.load_table(identifier)
    snapshot = table.current_snapshot()
    if snapshot is None or snapshot.summary is None:
        return 0
    return int(snapshot.summary["added-records"])


# ── test ──────────────────────────────────────────────────────────────────────


def test_bronze_to_silver_to_fatigue_end_to_end() -> None:
    game_pk = int(time.time() * 1000)
    base_time = datetime.now(UTC)

    low_pitcher_id = 910001
    medium_pitcher_id = 910002
    high_pitcher_id = 910003

    pitches: list[PitchEvent] = []
    pitches += _build_pitcher_pitches(
        game_pk=game_pk,
        pitcher_id=low_pitcher_id,
        batter_id=810001,
        count=10,
        at_bat_number=1,
        base_time=base_time,
    )
    pitches += _build_pitcher_pitches(
        game_pk=game_pk,
        pitcher_id=medium_pitcher_id,
        batter_id=810002,
        count=35,
        at_bat_number=2,
        base_time=base_time + timedelta(minutes=5),
    )
    pitches += _build_pitcher_pitches(
        game_pk=game_pk,
        pitcher_id=high_pitcher_id,
        batter_id=810003,
        count=75,
        at_bat_number=3,
        base_time=base_time + timedelta(minutes=15),
    )
    assert len(pitches) == 120

    # Step 1: inject into Iceberg bronze so the run.sh materialization step
    # picks up the synthetic rows (direct DuckDB writes would be overwritten).
    _append_to_iceberg_bronze(pitches, E2E_SOURCE_OFFSET_BASE)

    # Step 2: run the full wrapper — materialize, dbt, publish.
    _run_dbt_run_sh_full_refresh()

    # Step 3: verify DuckDB silver — filter by game_pk so prior bronze rows
    # (from earlier ingestion) do not affect the count.
    pitch_count = _silver_pitch_event_count_for_game(game_pk)
    assert pitch_count == 120, (
        f"Expected 120 rows in silver_pitch_events for game_pk={game_pk}, got {pitch_count}"
    )

    fatigue = _silver_fatigue_rows_for_game(game_pk)
    assert len(fatigue) == 3, f"Expected 3 fatigue rows for game_pk={game_pk}, got {fatigue}"
    assert fatigue[low_pitcher_id] == (10, "low"), fatigue[low_pitcher_id]
    assert fatigue[medium_pitcher_id] == (35, "medium"), fatigue[medium_pitcher_id]
    assert fatigue[high_pitcher_id] == (75, "high"), fatigue[high_pitcher_id]

    # Step 4: verify Iceberg silver snapshots reflect a recent publish.
    # added-records is the count appended in the most recent snapshot write.
    # With --full-refresh the DuckDB silver is rebuilt from all bronze rows
    # (existing 13 + synthetic 120 = 133+), so added-records >= 120.
    pitch_events_added = _iceberg_snapshot_added_records("silver.pitch_events")
    assert pitch_events_added >= 120, (
        f"Expected silver.pitch_events added-records >= 120, got {pitch_events_added}"
    )

    fatigue_added = _iceberg_snapshot_added_records("silver.pitcher_game_fatigue")
    assert fatigue_added >= 3, (
        f"Expected silver.pitcher_game_fatigue added-records >= 3, got {fatigue_added}"
    )
