"""End-to-end integration test for the Phase 1 smoke Flink job.

Submits the smoke job to the running Flink cluster, publishes 3 synthetic
PitchEvents to pitches.raw via the project's AvroEventPublisher, and asserts
that 3 corresponding "[smoke_job] pitcher=... event_time_ms=..." lines
appear in the TaskManager stdout within a bounded timeout.

This test is hermetic in the sense that it does NOT use the replay engine
(no pybaseball, no internet). It only uses the AvroEventPublisher directly,
which is what we want to exercise here: the wire from a Confluent-framed
Avro payload on Kafka to a Python operator inside Flink decoding it.

Run with:  pytest tests/integration/test_smoke_job.py -v
Or with:   pytest -m integration

Skipped by the default `pytest` invocation via the addopts marker filter.
"""

from __future__ import annotations

import re
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from infra.scripts.create_bronze_tables import ensure_bronze_pitches_table
from ingestion.replay_engine.avro_publisher import AvroEventPublisher
from ingestion.replay_engine.events import PitchEvent
from tests.integration.conftest import BOOTSTRAP_SERVERS, SCHEMA_REGISTRY_URL

pytestmark = [pytest.mark.integration, pytest.mark.slow]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

JOBMANAGER_CONTAINER = "bullpen-flink-jm"
TASKMANAGER_CONTAINER = "bullpen-flink-tm"
SMOKE_JOB_HOST_PATH = Path("streaming/flink_jobs/_smoke/job.py")
SMOKE_JOB_CONTAINER_PATH = "/tmp/smoke_job_test.py"

JOB_RUNNING_TIMEOUT = 30.0  # seconds to wait for job state RUNNING
SMOKE_OUTPUT_TIMEOUT = 30.0  # seconds to wait for N smoke lines to appear
POLL_INTERVAL = 1.0


# ---------------------------------------------------------------------------
# Flink lifecycle helpers (subprocess-based; the test does not use pyflink)
# ---------------------------------------------------------------------------


def _docker_exec(*args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    """Wrapper for `docker exec <container> <args>` returning CompletedProcess."""
    return subprocess.run(
        ["docker", "exec", *args],
        capture_output=True,
        text=True,
        check=check,
    )


def _submit_smoke_job() -> str:
    """Copy job.py into the JM container and submit it. Returns the JobID."""
    ensure_bronze_pitches_table()

    if not SMOKE_JOB_HOST_PATH.exists():
        pytest.fail(f"smoke job source not found at {SMOKE_JOB_HOST_PATH}")

    # Copy the source file into the container
    cp = subprocess.run(
        [
            "docker",
            "cp",
            str(SMOKE_JOB_HOST_PATH),
            f"{JOBMANAGER_CONTAINER}:{SMOKE_JOB_CONTAINER_PATH}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if cp.returncode != 0:
        pytest.fail(f"docker cp failed: {cp.stderr}")

    # Submit. --detached so flink run returns immediately.
    submit = _docker_exec(
        JOBMANAGER_CONTAINER,
        "/opt/flink/bin/flink",
        "run",
        "-py",
        SMOKE_JOB_CONTAINER_PATH,
        "--detached",
    )
    if submit.returncode != 0:
        pytest.fail(f"flink run failed:\nstdout:\n{submit.stdout}\nstderr:\n{submit.stderr}")

    # Output contains a line like:
    #   Job has been submitted with JobID 53b1cdd4021908917d8c9b6efb787492
    match = re.search(r"JobID ([0-9a-f]{32})", submit.stdout + submit.stderr)
    if not match:
        pytest.fail(
            f"could not parse JobID from flink run output:\n{submit.stdout}\n{submit.stderr}"
        )
    return match.group(1)


def _flink_list() -> str:
    """Return the raw output of `flink list` from inside the JM container."""
    res = _docker_exec(JOBMANAGER_CONTAINER, "/opt/flink/bin/flink", "list")
    return res.stdout + res.stderr


def _wait_for_job_running(job_id: str, timeout: float) -> None:
    """Poll `flink list` until the given JobID shows state RUNNING."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        listing = _flink_list()
        # `flink list` prints lines like:
        #   28.04.2026 20:20:37 : 53b1cdd4... : bullpen-signal smoke job ... (RUNNING)
        for line in listing.splitlines():
            if job_id in line and "(RUNNING)" in line:
                return
        time.sleep(POLL_INTERVAL)
    pytest.fail(
        f"job {job_id} did not reach RUNNING within {timeout}s. Last listing:\n{_flink_list()}"
    )


def _cancel_job(job_id: str) -> None:
    """Cancel a running job. Best-effort: errors here don't fail the test."""
    _docker_exec(
        JOBMANAGER_CONTAINER,
        "/opt/flink/bin/flink",
        "cancel",
        job_id,
    )


# ---------------------------------------------------------------------------
# TaskManager output observation
# ---------------------------------------------------------------------------


SMOKE_LINE_RE = re.compile(r"\[smoke_job\][^+]*\+I\[(\d+),\s*(\d+)\]")


def _get_tm_smoke_lines() -> list[tuple[int, int]]:
    """Read TM logs and return all parsed (pitcher_id, event_time_ms) pairs."""
    res = subprocess.run(
        ["docker", "logs", TASKMANAGER_CONTAINER],
        capture_output=True,
        text=True,
        check=False,
    )
    pairs: list[tuple[int, int]] = []
    for line in (res.stdout + res.stderr).splitlines():
        m = SMOKE_LINE_RE.search(line)
        if m:
            pairs.append((int(m.group(1)), int(m.group(2))))
    return pairs


def _wait_for_n_smoke_lines(
    expected: int, since_count: int, timeout: float
) -> list[tuple[int, int]]:
    """Poll TM logs until at least `expected` NEW smoke lines appear (above
    `since_count`), or timeout. Returns ALL accumulated smoke lines."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        pairs = _get_tm_smoke_lines()
        if len(pairs) - since_count >= expected:
            return pairs
        time.sleep(POLL_INTERVAL)
    pairs = _get_tm_smoke_lines()
    pytest.fail(
        f"expected {expected} new [smoke_job] lines (above baseline {since_count}); "
        f"saw {len(pairs) - since_count}. Total now: {len(pairs)}. Tail:\n"
        + "\n".join(f"  {p}" for p in pairs[-5:])
    )


def _wait_for_smoke_pitcher_ids(
    expected_pitcher_ids: set[int],
    *,
    since_count: int,
    timeout: float,
) -> list[tuple[int, int]]:
    """Poll TM logs until all expected pitcher IDs appear in new smoke lines."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        pairs = _get_tm_smoke_lines()
        new_pairs = pairs[since_count:]
        seen_pitcher_ids = {pitcher_id for pitcher_id, _ in new_pairs}
        if expected_pitcher_ids.issubset(seen_pitcher_ids):
            return new_pairs
        time.sleep(POLL_INTERVAL)

    pairs = _get_tm_smoke_lines()
    new_pairs = pairs[since_count:]
    seen_pitcher_ids = {pitcher_id for pitcher_id, _ in new_pairs}
    pytest.fail(
        "expected pitcher IDs did not all appear in new [smoke_job] lines. "
        f"missing={sorted(expected_pitcher_ids - seen_pitcher_ids)} "
        f"seen={sorted(seen_pitcher_ids)} "
        f"tail={new_pairs[-8:]}"
    )


# ---------------------------------------------------------------------------
# Synthetic data
# ---------------------------------------------------------------------------


def _build_synthetic_pitches(n: int) -> list[PitchEvent]:
    """Produce N distinct PitchEvents that the smoke job will decode and print.

    Pitcher IDs and event_times differ per pitch so we can match them
    individually in the assertion.
    """
    base = datetime(2024, 7, 4, 19, 0, 0, tzinfo=UTC)
    pitches: list[PitchEvent] = []
    for i in range(n):
        pitches.append(
            PitchEvent(
                event_time=base.replace(second=i * 10),
                ingest_time=base.replace(second=i * 10),
                game_pk=999_001,
                at_bat_number=1,
                pitch_number=i + 1,
                inning=1,
                inning_topbot="Top",
                pitcher_id=605_400 + i,  # 605400, 605401, 605402 — distinct
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


# ---------------------------------------------------------------------------
# The test
# ---------------------------------------------------------------------------


def test_smoke_job_decodes_avro_pitches_from_kafka(clean_topic) -> None:
    """Submit smoke job → publish 3 synthetic Avro pitches → assert TM stdout."""
    clean_topic("pitches.raw")

    # Snapshot any pre-existing [smoke_job] lines (from previous runs) so the
    # poll-after-publish only counts NEW lines from this test.
    baseline = len(_get_tm_smoke_lines())

    job_id = _submit_smoke_job()
    try:
        _wait_for_job_running(job_id, timeout=JOB_RUNNING_TIMEOUT)

        publisher = AvroEventPublisher(
            bootstrap_servers=BOOTSTRAP_SERVERS,
            schema_registry_url=SCHEMA_REGISTRY_URL,
            client_id="integration-test-smoke",
        )
        pitches = _build_synthetic_pitches(3)
        for pitch in pitches:
            publisher.publish(
                topic="pitches.raw",
                key=str(pitch.pitcher_id),
                event=pitch,
            )
        remaining = publisher.flush(timeout=10.0)
        assert remaining == 0, f"{remaining} messages failed to flush"

        expected_pitcher_ids = {pitch.pitcher_id for pitch in pitches}
        new_lines = _wait_for_smoke_pitcher_ids(
            expected_pitcher_ids,
            since_count=baseline,
            timeout=SMOKE_OUTPUT_TIMEOUT,
        )

        seen_pitcher_ids = {pid for pid, _ in new_lines}
        assert expected_pitcher_ids.issubset(seen_pitcher_ids), (
            f"missing pitcher IDs {expected_pitcher_ids - seen_pitcher_ids}. New lines: {new_lines}"
        )

    finally:
        _cancel_job(job_id)
