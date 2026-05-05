from pyiceberg.types import IntegerType, LongType, StringType, TimestamptzType

from lakehouse.schemas.silver_pitcher_game_fatigue import (
    SILVER_PITCHER_GAME_FATIGUE_IDENTIFIER,
    SILVER_PITCHER_GAME_FATIGUE_LOCATION,
    SILVER_PITCHER_GAME_FATIGUE_PARTITION_SPEC,
    SILVER_PITCHER_GAME_FATIGUE_SCHEMA,
)


def _fields_by_name():
    return {field.name: field for field in SILVER_PITCHER_GAME_FATIGUE_SCHEMA.fields}


def test_silver_pitcher_game_fatigue_identifier_and_location_are_stable() -> None:
    assert SILVER_PITCHER_GAME_FATIGUE_IDENTIFIER == "silver.pitcher_game_fatigue"
    assert (
        SILVER_PITCHER_GAME_FATIGUE_LOCATION == "s3://bullpen-warehouse/silver/pitcher_game_fatigue"
    )


def test_silver_pitcher_game_fatigue_schema_contains_expected_contract() -> None:
    fields = _fields_by_name()

    assert len(fields) == 10
    assert fields["game_pk"].field_type == LongType()
    assert fields["pitcher_id"].field_type == LongType()
    assert fields["first_pitch_time"].field_type == TimestamptzType()
    assert fields["last_pitch_time"].field_type == TimestamptzType()
    assert fields["pitch_count"].field_type == IntegerType()
    assert fields["max_inning"].field_type == IntegerType()
    assert fields["fatigue_bucket"].field_type == StringType()
    assert fields["fatigue_bucket"].required is True
    assert fields["computed_at"].field_type == TimestamptzType()


def test_silver_pitcher_game_fatigue_is_small_unpartitioned_snapshot_table() -> None:
    assert SILVER_PITCHER_GAME_FATIGUE_PARTITION_SPEC.fields == ()
