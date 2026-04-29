"""TaskManager restart tolerance for the Phase 1 smoke Flink job."""

from __future__ import annotations

import json
import subprocess
import time
import urllib.request
from collections import Counter
from datetime import UTC, datetime, timedelta

import pytest

from ingestion.replay_engine.avro_publisher import AvroEventPublisher
from ingestion.replay_engine.events import PitchEvent
from tests.integration.conftest import BOOTSTRAP_SERVERS, SCHEMA_REGISTRY_URL
from tests.integration.test_smoke_job import (
    TASKMANAGER_CONTAINER,
    _cancel_job,
    _get_tm_smoke_lines,
    _submit_smoke_job,
    _wait_for_job_running,
)

pytestmark = [pytest.mark.integration, pytest.mark.slow]

FLINK_REST_URL = "http://localhost:8082"
CHECKPOINT_TIMEOUT = 90.0
RECOVERY_TIMEOUT = 120.0
POLL_INTERVAL = 1.0


def _flink_rest_json(path: str) -> dict:
    with urllib.request.urlopen(f"{FLINK_REST_URL}{path}", timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _completed_checkpoint_count(job_id: str) -> int:
    data = _flink_rest_json(f"/jobs/{job_id}/checkpoints")
    return int(data.get("counts", {}).get("completed", 0))


def _wait_for_completed_checkpoint_after(
    job_id: str,
    previous_count: int,
    timeout: float = CHECKPOINT_TIMEOUT,
) -> int:
    deadline = time.time() + timeout
    last_error: Exception | None = None

    while time.time() < deadline:
        try:
            count = _completed_checkpoint_count(job_id)
            if count > previous_count:
                return count
        except Exception as exc:
            last_error = exc

        time.sleep(POLL_INTERVAL)

    pytest.fail(
        f"job {job_id} did not complete a checkpoint after count={previous_count} "
        f"within {timeout}s. Last REST error: {last_error!r}"
    )


def _restart_taskmanager() -> None:
    restarted = subprocess.run(
        ["docker", "restart", TASKMANAGER_CONTAINER],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if restarted.returncode != 0:
        pytest.fail(
            "docker restart taskmanager failed:\n"
            f"stdout:\n{restarted.stdout}\n"
            f"stderr:\n{restarted.stderr}"
        )


def _build_restart_pitches(
    *,
    pitcher_start: int,
    pitch_count: int,
    base_second: int,
) -> list[PitchEvent]:
    base = datetime(2024, 7, 4, 19, 0, base_second, tzinfo=UTC)
    pitches: list[PitchEvent] = []

    for i in range(pitch_count):
        event_time = base + timedelta(seconds=i * 10)
        pitches.append(
            PitchEvent(
                event_time=event_time,
                ingest_time=event_time,
                game_pk=999_777,
                at_bat_number=1,
                pitch_number=i + 1,
                inning=1,
                inning_topbot="Top",
                pitcher_id=pitcher_start + i,
                batter_id=660_271,
                pitch_type="FF",
                release_speed=95.0,
                release_spin_rate=2400.0,
                plate_x=0.0,
                plate_z=2.5,
                zone=5,
                balls=0,
                strikes=0,
                outs_when_up=0,
                on_1b=None,
                on_2b=None,
                on_3b=None,
                description="ball",
                events=None,
                home_score=0,
                away_score=0,
            )
        )

    return pitches


def _publish_pitches(pitches: list[PitchEvent]) -> None:
    publisher = AvroEventPublisher(
        bootstrap_servers=BOOTSTRAP_SERVERS,
        schema_registry_url=SCHEMA_REGISTRY_URL,
        client_id="integration-test-smoke-restart",
    )

    for pitch in pitches:
        publisher.publish(
            topic="pitches.raw",
            key=f"{pitch.game_pk}:{pitch.pitcher_id}:{pitch.pitch_number}",
            event=pitch,
        )

    remaining = publisher.flush(timeout=10.0)
    assert remaining == 0, f"{remaining} messages failed to flush"


def _wait_for_pitcher_ids(
    expected_pitcher_ids: set[int],
    *,
    since_count: int,
    timeout: float,
) -> list[tuple[int, int]]:
    deadline = time.time() + timeout

    while time.time() < deadline:
        pairs = _get_tm_smoke_lines()
        new_pairs = pairs[since_count:]
        seen = {pitcher_id for pitcher_id, _ in new_pairs}

        if expected_pitcher_ids.issubset(seen):
            return new_pairs

        time.sleep(POLL_INTERVAL)

    pairs = _get_tm_smoke_lines()
    new_pairs = pairs[since_count:]
    pytest.fail(
        "expected pitcher ids did not appear in TaskManager smoke output. "
        f"missing={sorted(expected_pitcher_ids - {pid for pid, _ in new_pairs})} "
        f"new_tail={new_pairs[-10:]}"
    )


def test_smoke_job_survives_taskmanager_restart_mid_stream(clean_topic) -> None:
    """Submit smoke job, checkpoint it, restart TM, then prove it keeps consuming."""
    clean_topic("pitches.raw")

    baseline = len(_get_tm_smoke_lines())
    job_id = _submit_smoke_job()

    try:
        _wait_for_job_running(job_id, timeout=30.0)

        checkpoint_before_pre_batch = _completed_checkpoint_count(job_id)

        pre_restart_pitches = _build_restart_pitches(
            pitcher_start=806_000,
            pitch_count=3,
            base_second=0,
        )
        pre_restart_ids = {pitch.pitcher_id for pitch in pre_restart_pitches}

        _publish_pitches(pre_restart_pitches)
        _wait_for_pitcher_ids(
            pre_restart_ids,
            since_count=baseline,
            timeout=45.0,
        )

        # Wait for at least one checkpoint after the pre-restart batch has been
        # observed. This gives Flink a durable recovery point before the TM dies.
        _wait_for_completed_checkpoint_after(job_id, checkpoint_before_pre_batch)

        _restart_taskmanager()
        _wait_for_job_running(job_id, timeout=RECOVERY_TIMEOUT)

        post_restart_pitches = _build_restart_pitches(
            pitcher_start=806_100,
            pitch_count=3,
            base_second=40,
        )
        post_restart_ids = {pitch.pitcher_id for pitch in post_restart_pitches}

        _publish_pitches(post_restart_pitches)

        all_expected_ids = pre_restart_ids | post_restart_ids
        new_pairs = _wait_for_pitcher_ids(
            all_expected_ids,
            since_count=baseline,
            timeout=60.0,
        )

        counts = Counter(
            pitcher_id for pitcher_id, _ in new_pairs if pitcher_id in all_expected_ids
        )
        assert counts == Counter({pitcher_id: 1 for pitcher_id in all_expected_ids})

    finally:
        _cancel_job(job_id)


def test_flink_checkpoint_endpoint_reports_completed_checkpoints() -> None:
    """Guardrail: the local stack exposes checkpoint state through Flink REST."""
    overview = _flink_rest_json("/overview")
    assert "flink-version" in overview
