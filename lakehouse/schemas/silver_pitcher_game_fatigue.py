"""Schema definition for the silver pitcher game fatigue Iceberg table."""

from __future__ import annotations

from pyiceberg.partitioning import PartitionSpec
from pyiceberg.schema import Schema
from pyiceberg.types import (
    DoubleType,
    IntegerType,
    LongType,
    NestedField,
    StringType,
    TimestamptzType,
)

SILVER_PITCHER_GAME_FATIGUE_NAMESPACE = "silver"
SILVER_PITCHER_GAME_FATIGUE_TABLE = "pitcher_game_fatigue"
SILVER_PITCHER_GAME_FATIGUE_IDENTIFIER = (
    f"{SILVER_PITCHER_GAME_FATIGUE_NAMESPACE}.{SILVER_PITCHER_GAME_FATIGUE_TABLE}"
)
SILVER_PITCHER_GAME_FATIGUE_LOCATION = "s3://bullpen-warehouse/silver/pitcher_game_fatigue"

SILVER_PITCHER_GAME_FATIGUE_SCHEMA = Schema(
    NestedField(field_id=1, name="game_pk", field_type=LongType(), required=True),
    NestedField(field_id=2, name="pitcher_id", field_type=LongType(), required=True),
    NestedField(field_id=3, name="first_pitch_time", field_type=TimestamptzType(), required=True),
    NestedField(field_id=4, name="last_pitch_time", field_type=TimestamptzType(), required=True),
    NestedField(field_id=5, name="pitch_count", field_type=IntegerType(), required=True),
    NestedField(field_id=6, name="max_inning", field_type=IntegerType(), required=True),
    NestedField(field_id=7, name="avg_release_speed", field_type=DoubleType(), required=False),
    NestedField(field_id=8, name="avg_release_spin_rate", field_type=DoubleType(), required=False),
    NestedField(field_id=9, name="fatigue_bucket", field_type=StringType(), required=True),
    NestedField(field_id=10, name="computed_at", field_type=TimestamptzType(), required=True),
)

SILVER_PITCHER_GAME_FATIGUE_PARTITION_SPEC = PartitionSpec()
