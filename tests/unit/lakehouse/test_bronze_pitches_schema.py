from __future__ import annotations

from lakehouse.schemas.bronze_pitches import (
    BRONZE_PITCHES_IDENTIFIER,
    BRONZE_PITCHES_LOCATION,
    BRONZE_PITCHES_PARTITION_SPEC,
    bronze_pitches_field_names,
)


def test_bronze_pitches_identifier_and_location_are_stable() -> None:
    assert BRONZE_PITCHES_IDENTIFIER == "bronze.pitches"
    assert BRONZE_PITCHES_LOCATION == "s3://bullpen-warehouse/bronze/pitches"


def test_bronze_pitches_schema_contains_avro_fields_plus_audit_fields() -> None:
    fields = bronze_pitches_field_names()

    assert fields[:3] == ["event_time", "ingest_time", "game_pk"]
    assert "pitcher_id" in fields
    assert "is_late_arrival" in fields
    assert "is_duplicate" in fields
    assert fields[-2:] == ["ingestion_time", "source_offset"]


def test_bronze_pitches_partitions_by_ingestion_day() -> None:
    partition_field = BRONZE_PITCHES_PARTITION_SPEC.fields[0]

    assert partition_field.source_id == 29
    assert partition_field.name == "ingestion_day"
    assert "day" in repr(partition_field.transform).lower()
