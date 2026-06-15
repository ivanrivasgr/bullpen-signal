from __future__ import annotations

from tests._paths import REPO_ROOT

MODEL_SQL = (REPO_ROOT / "dbt/models/silver/silver_pitch_events.sql").read_text()
RUN_SH = (REPO_ROOT / "dbt/run.sh").read_text()
SOURCES_YML = (REPO_ROOT / "dbt/models/sources.yml").read_text()
SILVER_YML = (REPO_ROOT / "dbt/models/silver/_silver.yml").read_text()
UNIQUE_TEST_SQL = (REPO_ROOT / "dbt/tests/unique_silver_pitch_events_natural_key.sql").read_text()


def _compact(value: str) -> str:
    return " ".join(value.lower().split())


def test_incremental_model_uses_natural_composite_key() -> None:
    compact = _compact(MODEL_SQL)
    assert 'materialized="incremental"' in compact
    assert 'unique_key=["game_pk", "at_bat_number", "pitch_number"]' in compact
    assert "pitch_id" not in compact


def test_model_reads_bronze_source_through_dbt_source() -> None:
    compact = _compact(MODEL_SQL)
    assert '{{ source("bronze", "pitches") }}' in compact
    assert "iceberg_scan" not in compact
    assert "s3://" not in compact


def test_model_derives_event_day_from_event_time() -> None:
    compact = _compact(MODEL_SQL)
    assert "cast(event_time as date) as event_day" in compact


def test_model_preserves_provenance_and_audit_columns() -> None:
    compact = _compact(MODEL_SQL)
    for column in [
        "is_late_arrival",
        "is_duplicate",
        "correction_of",
        "ingestion_time",
        "kafka_partition",
        "source_offset",
    ]:
        assert column in compact


def test_model_does_not_filter_duplicate_or_late_arrival_flags() -> None:
    compact = _compact(MODEL_SQL)
    assert "where is_duplicate" not in compact
    assert "where not is_duplicate" not in compact
    assert "where is_late_arrival" not in compact


def test_bronze_source_is_direct_relation_materialized_before_dbt_run() -> None:
    compact_sources = _compact(SOURCES_YML)
    assert "schema: bronze" in compact_sources
    assert "- name: pitches" in compact_sources
    assert "external_location" not in compact_sources
    assert "iceberg_scan" not in compact_sources
    assert "materialize_dbt_sources.py" in RUN_SH


def test_dbt_contract_has_key_not_null_tests_and_custom_unique_test() -> None:
    compact_yml = _compact(SILVER_YML)
    compact_unique = _compact(UNIQUE_TEST_SQL)
    for column in ["game_pk", "at_bat_number", "pitch_number"]:
        assert f"name: {column}" in compact_yml
    assert 'from {{ ref("silver_pitch_events") }}' in compact_unique
    assert "group by game_pk, at_bat_number, pitch_number" in compact_unique
    assert "having count(*) > 1" in compact_unique
