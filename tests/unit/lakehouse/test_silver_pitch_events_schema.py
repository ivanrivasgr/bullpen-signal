from pyiceberg.transforms import IdentityTransform
from pyiceberg.types import DateType, IntegerType, LongType, TimestamptzType

from lakehouse.schemas.silver_pitch_events import (
    SILVER_PITCH_EVENTS_IDENTIFIER,
    SILVER_PITCH_EVENTS_LOCATION,
    SILVER_PITCH_EVENTS_PARTITION_SPEC,
    SILVER_PITCH_EVENTS_SCHEMA,
)


def _fields_by_name():
    return {field.name: field for field in SILVER_PITCH_EVENTS_SCHEMA.fields}


def test_silver_pitch_events_identifier_and_location_are_stable() -> None:
    assert SILVER_PITCH_EVENTS_IDENTIFIER == "silver.pitch_events"
    assert SILVER_PITCH_EVENTS_LOCATION == "s3://bullpen-warehouse/silver/pitch_events"


def test_silver_pitch_events_schema_contains_expected_contract() -> None:
    fields = _fields_by_name()

    assert len(fields) == 31
    assert "pitch_id" not in fields
    assert fields["event_time"].field_type == TimestamptzType()
    assert fields["event_time"].required is True
    assert fields["event_day"].field_type == DateType()
    assert fields["game_pk"].field_type == LongType()
    assert fields["at_bat_number"].field_type == IntegerType()
    assert fields["pitch_number"].field_type == IntegerType()


def test_silver_pitch_events_preserves_bronze_audit_and_provenance_columns() -> None:
    fields = _fields_by_name()

    for name in [
        "is_late_arrival",
        "is_duplicate",
        "correction_of",
        "ingestion_time",
        "kafka_partition",
        "source_offset",
    ]:
        assert name in fields


def test_silver_pitch_events_partitions_by_event_day() -> None:
    [field] = SILVER_PITCH_EVENTS_PARTITION_SPEC.fields
    assert field.source_id == 2
    assert field.name == "event_day"
    assert isinstance(field.transform, IdentityTransform)
