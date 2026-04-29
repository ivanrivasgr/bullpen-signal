"""Unit tests for the smoke job SQL definitions.

These tests intentionally avoid importing PyFlink. The smoke job imports PyFlink
inside main() so CI can validate the SQL-building logic without a Flink runtime.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_smoke_job_module():
    repo_root = Path(__file__).parents[3]
    job_path = repo_root / "streaming/flink_jobs/_smoke/job.py"
    spec = importlib.util.spec_from_file_location("smoke_job", job_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


smoke_job = _load_smoke_job_module()


def test_source_ddl_declares_event_time_watermark() -> None:
    ddl = smoke_job.build_pitches_source_ddl()

    assert "event_ts AS TO_TIMESTAMP_LTZ(event_time, 3)" in ddl
    assert "WATERMARK FOR event_ts AS event_ts - INTERVAL '5' MINUTE" in ddl


def test_source_ddl_uses_avro_confluent_format() -> None:
    ddl = smoke_job.build_pitches_source_ddl()

    assert "'value.format' = 'avro-confluent'" in ddl
    assert "'value.avro-confluent.url' = 'http://redpanda:18081'" in ddl


def test_source_ddl_starts_from_earliest_offsets_for_repeatable_smoke_tests() -> None:
    ddl = smoke_job.build_pitches_source_ddl()

    assert "'scan.startup.mode' = 'earliest-offset'" in ddl
    assert "'properties.group.id' = 'bullpen-smoke-job'" in ddl


def test_insert_projects_only_print_sink_columns() -> None:
    sql = smoke_job.build_smoke_insert_sql()

    assert "SELECT pitcher_id, event_time" in sql
    assert "event_ts" not in sql
