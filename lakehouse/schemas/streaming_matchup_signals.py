"""Schema definition for the streaming matchup signals Iceberg table.

The streaming matchup job writes its signal rows here. The columns are
the contract fixed by ADR 0022: exactly what the reconciliation layer
(mart_should_have_fired_ledger) and the revision producer read from the
batch signal table, and nothing inherited beyond that. The batch table
silver_matchup_signals is wider — it carries fields inherited from
silver_matchup_events — but the reconciliation joins on the natural key
and reads only these contract columns, so the two paths compare
apples to apples on them.

Natural key: (game_pk, at_bat_number, pitch_number, lineup_state_at_emission).
The emission state is part of the key because an uncertain pitch emits two
rows — reduced and full — that share the first three fields (ADR 0020).
"""

from __future__ import annotations

from pyiceberg.partitioning import PartitionField, PartitionSpec
from pyiceberg.schema import Schema
from pyiceberg.transforms import DayTransform
from pyiceberg.types import (
    DoubleType,
    IntegerType,
    LongType,
    NestedField,
    StringType,
    TimestamptzType,
)

STREAMING_MATCHUP_SIGNALS_NAMESPACE = "streaming"
STREAMING_MATCHUP_SIGNALS_TABLE = "matchup_signals"
STREAMING_MATCHUP_SIGNALS_IDENTIFIER = (
    f"{STREAMING_MATCHUP_SIGNALS_NAMESPACE}.{STREAMING_MATCHUP_SIGNALS_TABLE}"
)
STREAMING_MATCHUP_SIGNALS_LOCATION = "s3://bullpen-warehouse/streaming/matchup_signals"

STREAMING_MATCHUP_SIGNALS_SCHEMA = Schema(
    # Identity / timing.
    NestedField(field_id=1, name="event_time", field_type=TimestamptzType(), required=True),
    # Natural key (game_pk, at_bat_number, pitch_number, lineup_state_at_emission).
    NestedField(field_id=2, name="game_pk", field_type=LongType(), required=True),
    NestedField(field_id=3, name="at_bat_number", field_type=IntegerType(), required=True),
    NestedField(field_id=4, name="pitch_number", field_type=IntegerType(), required=True),
    # Matchup participants.
    NestedField(field_id=5, name="pitcher_id", field_type=LongType(), required=True),
    NestedField(field_id=6, name="batter_id", field_type=LongType(), required=True),
    # Signal. handedness_matchup is nullable: a player absent from the
    # handedness seed yields a null matchup, exactly as in the batch path.
    NestedField(field_id=7, name="handedness_matchup", field_type=StringType(), required=False),
    NestedField(field_id=8, name="signal_value", field_type=DoubleType(), required=True),
    NestedField(field_id=9, name="confidence_band", field_type=StringType(), required=True),
    NestedField(
        field_id=10,
        name="lineup_state_at_emission",
        field_type=StringType(),
        required=True,
    ),
)

STREAMING_MATCHUP_SIGNALS_PARTITION_SPEC = PartitionSpec(
    PartitionField(
        source_id=1,
        field_id=1000,
        transform=DayTransform(),
        name="event_day",
    )
)
