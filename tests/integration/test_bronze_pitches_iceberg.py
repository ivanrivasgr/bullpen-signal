"""Integration coverage for the durable bronze Iceberg smoke path."""

from __future__ import annotations

import subprocess
import time

import pytest

from infra.scripts.create_bronze_tables import ensure_bronze_pitches_table
from ingestion.replay_engine.avro_publisher import AvroEventPublisher
from ingestion.replay_engine.events import PitchEvent
from lakehouse.query import count_rows, query, query_snapshot, table_metadata_location
from tests.integration.conftest import BOOTSTRAP_SERVERS, SCHEMA_REGISTRY_URL
from tests.integration.test_smoke_job import (
    JOB_RUNNING_TIMEOUT,
    POLL_INTERVAL,
    SMOKE_OUTPUT_TIMEOUT,
    _build_synthetic_pitches,
    _get_tm_smoke_lines,
    _submit_smoke_job,
    _wait_for_job_running,
    _wait_for_smoke_pitcher_ids,
)

pytestmark = [pytest.mark.integration, pytest.mark.slow]

ICEBERG_COMMIT_TIMEOUT = 150.0


def _copy_pitch(pitch: PitchEvent, **updates: object) -> PitchEvent:
    if hasattr(pitch, "model_copy"):
        return pitch.model_copy(update=updates)
    return pitch.copy(update=updates)


def _cancel_job(job_id: str) -> None:
    subprocess.run(
        ["docker", "exec", "bullpen-flink-jm", "/opt/flink/bin/flink", "cancel", job_id],
        capture_output=True,
        text=True,
        check=False,
    )


def _wait_for_bronze_count(game_pk: int, expected: int, timeout: float) -> None:
    deadline = time.time() + timeout
    where = f"game_pk = {game_pk}"

    while time.time() < deadline:
        if count_rows("bronze.pitches", where=where) == expected:
            return
        time.sleep(POLL_INTERVAL)

    actual = count_rows("bronze.pitches", where=where)
    pytest.fail(f"expected {expected} bronze rows for game_pk={game_pk}; saw {actual}")


def test_smoke_job_commits_pitches_to_bronze_iceberg(clean_topic) -> None:
    ensure_bronze_pitches_table()
    clean_topic("pitches.raw")

    game_pk = int(time.time() * 1000)
    baseline = len(_get_tm_smoke_lines())
    metadata_before = table_metadata_location("bronze.pitches")

    pitches = [
        _copy_pitch(
            pitch,
            game_pk=game_pk,
            at_bat_number=50,
            pitch_number=index + 1,
            pitcher_id=705400 + index,
            batter_id=760270 + index,
        )
        for index, pitch in enumerate(_build_synthetic_pitches(4))
    ]

    assert count_rows("bronze.pitches", where=f"game_pk = {game_pk}") == 0

    job_id = _submit_smoke_job()
    try:
        _wait_for_job_running(job_id, timeout=JOB_RUNNING_TIMEOUT)

        publisher = AvroEventPublisher(
            bootstrap_servers=BOOTSTRAP_SERVERS,
            schema_registry_url=SCHEMA_REGISTRY_URL,
            client_id="integration-test-bronze-iceberg",
        )
        for pitch in pitches:
            publisher.publish("pitches.raw", str(pitch.pitcher_id), pitch)

        assert publisher.flush(timeout=10.0) == 0

        expected_pitcher_ids = {pitch.pitcher_id for pitch in pitches}
        _wait_for_smoke_pitcher_ids(
            expected_pitcher_ids,
            since_count=baseline,
            timeout=SMOKE_OUTPUT_TIMEOUT,
        )
        _wait_for_bronze_count(game_pk, expected=len(pitches), timeout=ICEBERG_COMMIT_TIMEOUT)
    finally:
        _cancel_job(job_id)

    metadata_after = table_metadata_location("bronze.pitches")
    assert metadata_after != metadata_before

    before_count = query_snapshot(
        f"SELECT COUNT(*) FROM bronze_pitches WHERE game_pk = {game_pk}",
        metadata_location=metadata_before,
    )[0][0]
    assert before_count == 0

    latest = query(
        f"""
        SELECT
            COUNT(*) AS rows,
            COUNT(DISTINCT pitcher_id) AS pitchers,
            COUNT(DISTINCT pitch_number) AS pitches
        FROM bronze_pitches
        WHERE game_pk = {game_pk}
        """
    )[0]
    assert latest == (4, 4, 4)
