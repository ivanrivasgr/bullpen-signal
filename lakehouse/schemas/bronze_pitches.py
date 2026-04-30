"""Iceberg schema-as-code for bronze.pitches."""

from __future__ import annotations

from pyiceberg.partitioning import PartitionField, PartitionSpec
from pyiceberg.schema import Schema
from pyiceberg.transforms import DayTransform
from pyiceberg.types import (
    BooleanType,
    DoubleType,
    IntegerType,
    LongType,
    NestedField,
    StringType,
    TimestamptzType,
)

BRONZE_PITCHES_IDENTIFIER = "bronze.pitches"
BRONZE_PITCHES_LOCATION = "s3://bullpen-warehouse/bronze/pitches"

BRONZE_PITCHES_SCHEMA = Schema(
    NestedField(field_id=1, name="event_time", field_type=LongType(), required=True),
    NestedField(field_id=2, name="ingest_time", field_type=LongType(), required=True),
    NestedField(field_id=3, name="game_pk", field_type=LongType(), required=True),
    NestedField(field_id=4, name="at_bat_number", field_type=IntegerType(), required=True),
    NestedField(field_id=5, name="pitch_number", field_type=IntegerType(), required=True),
    NestedField(field_id=6, name="inning", field_type=IntegerType(), required=True),
    NestedField(field_id=7, name="inning_topbot", field_type=StringType(), required=True),
    NestedField(field_id=8, name="pitcher_id", field_type=LongType(), required=True),
    NestedField(field_id=9, name="batter_id", field_type=LongType(), required=True),
    NestedField(field_id=10, name="pitch_type", field_type=StringType(), required=False),
    NestedField(field_id=11, name="release_speed", field_type=DoubleType(), required=False),
    NestedField(field_id=12, name="release_spin_rate", field_type=DoubleType(), required=False),
    NestedField(field_id=13, name="plate_x", field_type=DoubleType(), required=False),
    NestedField(field_id=14, name="plate_z", field_type=DoubleType(), required=False),
    NestedField(field_id=15, name="zone", field_type=IntegerType(), required=False),
    NestedField(field_id=16, name="balls", field_type=IntegerType(), required=True),
    NestedField(field_id=17, name="strikes", field_type=IntegerType(), required=True),
    NestedField(field_id=18, name="outs_when_up", field_type=IntegerType(), required=True),
    NestedField(field_id=19, name="on_1b", field_type=LongType(), required=False),
    NestedField(field_id=20, name="on_2b", field_type=LongType(), required=False),
    NestedField(field_id=21, name="on_3b", field_type=LongType(), required=False),
    NestedField(field_id=22, name="description", field_type=StringType(), required=False),
    NestedField(field_id=23, name="events", field_type=StringType(), required=False),
    NestedField(field_id=24, name="home_score", field_type=IntegerType(), required=True),
    NestedField(field_id=25, name="away_score", field_type=IntegerType(), required=True),
    NestedField(field_id=26, name="is_late_arrival", field_type=BooleanType(), required=True),
    NestedField(field_id=27, name="is_duplicate", field_type=BooleanType(), required=True),
    NestedField(field_id=28, name="correction_of", field_type=StringType(), required=False),
    NestedField(field_id=29, name="ingestion_time", field_type=TimestamptzType(), required=True),
    NestedField(field_id=30, name="source_offset", field_type=LongType(), required=True),
)

BRONZE_PITCHES_PARTITION_SPEC = PartitionSpec(
    PartitionField(
        source_id=29,
        field_id=1000,
        transform=DayTransform(),
        name="ingestion_day",
    )
)

BRONZE_PITCHES_PROPERTIES = {
    "format-version": "2",
    "write.format.default": "parquet",
}


def bronze_pitches_field_names() -> list[str]:
    return [field.name for field in BRONZE_PITCHES_SCHEMA.fields]
