from pyiceberg.transforms import DayTransform
from pyiceberg.types import IntegerType, LongType, TimestamptzType

from lakehouse.schemas.bronze_pitches import (
    BRONZE_PITCHES_IDENTIFIER,
    BRONZE_PITCHES_LOCATION,
    BRONZE_PITCHES_PARTITION_SPEC,
    BRONZE_PITCHES_SCHEMA,
)


def _fields_by_name():
    return {field.name: field for field in BRONZE_PITCHES_SCHEMA.fields}


def test_bronze_pitches_identifier_and_location_are_stable() -> None:
    assert BRONZE_PITCHES_IDENTIFIER == "bronze.pitches"
    assert BRONZE_PITCHES_LOCATION == "s3://bullpen-warehouse/bronze/pitches"


def test_bronze_pitches_schema_uses_event_time_and_audit_metadata() -> None:
    fields = _fields_by_name()

    assert len(fields) == 30
    assert "ingest_time" not in fields
    assert fields["event_time"].field_id == 1
    assert fields["event_time"].field_type == TimestamptzType()
    assert fields["event_time"].required is True
    assert fields["ingestion_time"].field_type == TimestamptzType()
    assert fields["source_offset"].field_type == LongType()
    assert fields["kafka_partition"].field_type == IntegerType()
    assert fields["kafka_partition"].required is True


def test_bronze_pitches_leaves_retired_field_id_two_unused() -> None:
    assert 2 not in {field.field_id for field in BRONZE_PITCHES_SCHEMA.fields}


def test_bronze_pitches_partitions_by_event_day() -> None:
    [field] = BRONZE_PITCHES_PARTITION_SPEC.fields
    assert field.source_id == 1
    assert field.name == "event_day"
    assert isinstance(field.transform, DayTransform)
