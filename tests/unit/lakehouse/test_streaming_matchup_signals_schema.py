from pyiceberg.transforms import DayTransform
from pyiceberg.types import (
    DoubleType,
    IntegerType,
    LongType,
    StringType,
    TimestamptzType,
)

from lakehouse.schemas.streaming_matchup_signals import (
    STREAMING_MATCHUP_SIGNALS_IDENTIFIER,
    STREAMING_MATCHUP_SIGNALS_LOCATION,
    STREAMING_MATCHUP_SIGNALS_PARTITION_SPEC,
    STREAMING_MATCHUP_SIGNALS_SCHEMA,
)


def _fields_by_name():
    return {field.name: field for field in STREAMING_MATCHUP_SIGNALS_SCHEMA.fields}


def test_streaming_matchup_signals_identifier_and_location_are_stable() -> None:
    assert STREAMING_MATCHUP_SIGNALS_IDENTIFIER == "streaming.matchup_signals"
    assert STREAMING_MATCHUP_SIGNALS_LOCATION == "s3://bullpen-warehouse/streaming/matchup_signals"


def test_streaming_matchup_signals_carries_exactly_the_adr_0022_contract() -> None:
    # ADR 0022: the streaming table carries exactly the ten columns the
    # reconciliation and revision producer read — no inherited width.
    fields = _fields_by_name()
    assert set(fields) == {
        "event_time",
        "game_pk",
        "at_bat_number",
        "pitch_number",
        "pitcher_id",
        "batter_id",
        "handedness_matchup",
        "signal_value",
        "confidence_band",
        "lineup_state_at_emission",
    }
    # The inherited columns the ADR deliberately excludes must not appear.
    for excluded in (
        "pitcher_fatigue_bucket",
        "pitcher_handedness",
        "batter_handedness",
        "projected_batter_id",
        "projected_handedness_matchup",
        "is_late_arrival",
        "is_duplicate",
        "correction_of",
        "computed_at",
    ):
        assert excluded not in fields


def test_streaming_matchup_signals_natural_key_types() -> None:
    fields = _fields_by_name()
    assert fields["event_time"].field_type == TimestamptzType()
    assert fields["event_time"].required is True
    assert fields["game_pk"].field_type == LongType()
    assert fields["game_pk"].required is True
    assert fields["at_bat_number"].field_type == IntegerType()
    assert fields["pitch_number"].field_type == IntegerType()
    # lineup_state_at_emission completes the natural key (ADR 0020) and is
    # required — every signal row records the state it was emitted under.
    assert fields["lineup_state_at_emission"].field_type == StringType()
    assert fields["lineup_state_at_emission"].required is True


def test_streaming_matchup_signals_signal_field_types() -> None:
    fields = _fields_by_name()
    assert fields["pitcher_id"].field_type == LongType()
    assert fields["batter_id"].field_type == LongType()
    assert fields["signal_value"].field_type == DoubleType()
    assert fields["signal_value"].required is True
    assert fields["confidence_band"].field_type == StringType()
    assert fields["confidence_band"].required is True
    # handedness_matchup is nullable: a player absent from the seed yields a
    # null matchup, matching the batch path (ADR 0022).
    assert fields["handedness_matchup"].field_type == StringType()
    assert fields["handedness_matchup"].required is False


def test_streaming_matchup_signals_partitions_by_event_day() -> None:
    [field] = STREAMING_MATCHUP_SIGNALS_PARTITION_SPEC.fields
    assert field.source_id == 1
    assert field.name == "event_day"
    assert isinstance(field.transform, DayTransform)
