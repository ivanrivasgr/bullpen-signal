from __future__ import annotations

import importlib.util
from pathlib import Path

SMOKE_JOB_PATH = Path("streaming/flink_jobs/_smoke/job.py")


def _load_smoke_job_module():
    spec = importlib.util.spec_from_file_location("smoke_job", SMOKE_JOB_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_table_config_sets_default_parallelism_to_two() -> None:
    job = _load_smoke_job_module()

    assert job.build_table_config_options() == {"table.exec.resource.default-parallelism": "2"}


def test_source_ddl_declares_event_time_watermark() -> None:
    job = _load_smoke_job_module()
    ddl = job.build_pitches_source_ddl()

    assert "event_ts AS TO_TIMESTAMP_LTZ(event_time, 3)" in ddl
    assert "WATERMARK FOR event_ts AS event_ts - INTERVAL '5' MINUTE" in ddl


def test_source_ddl_exposes_kafka_offset_metadata() -> None:
    job = _load_smoke_job_module()
    ddl = job.build_pitches_source_ddl()

    assert "source_offset BIGINT METADATA FROM 'offset' VIRTUAL" in ddl


def test_source_ddl_marks_required_avro_fields_not_null() -> None:
    job = _load_smoke_job_module()
    ddl = job.build_pitches_source_ddl()

    assert "event_time BIGINT NOT NULL" in ddl
    assert "inning_topbot STRING NOT NULL" in ddl
    assert "is_late_arrival BOOLEAN NOT NULL" in ddl


def test_source_ddl_uses_avro_confluent_format() -> None:
    job = _load_smoke_job_module()
    ddl = job.build_pitches_source_ddl()

    assert "'value.format' = 'avro-confluent'" in ddl
    assert "'value.avro-confluent.url'" in ddl


def test_raw_insert_projects_only_print_sink_columns() -> None:
    job = _load_smoke_job_module()
    sql = job.build_smoke_insert_sql()

    assert "SELECT pitcher_id, event_time" in sql
    assert "INTO smoke_sink" in sql


def test_counts_insert_groups_by_game_and_pitcher_key() -> None:
    job = _load_smoke_job_module()
    sql = job.build_smoke_counts_insert_sql()

    assert "TUMBLE(" in sql
    assert "GROUP BY game_pk, pitcher_id, window_start, window_end" in sql


def test_iceberg_catalog_uses_rest_catalog_and_minio_s3() -> None:
    job = _load_smoke_job_module()
    ddl = job.build_iceberg_catalog_ddl()

    assert "'catalog-type' = 'rest'" in ddl
    assert "'uri' = 'http://iceberg-rest:8181'" in ddl
    assert "'s3.endpoint' = 'http://minio:9000'" in ddl
    assert "'client.region' = 'us-east-1'" in ddl


def test_bronze_insert_writes_audit_columns() -> None:
    job = _load_smoke_job_module()
    sql = job.build_bronze_pitches_insert_sql()

    assert "INSERT INTO bullpen.bronze.pitches" in sql
    assert "CURRENT_TIMESTAMP AS ingestion_time" in sql
    assert "source_offset" in sql
