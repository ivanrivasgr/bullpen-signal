"""Create local Iceberg silver tables for development.

The --recreate option is destructive: it drops silver tables from the local
Iceberg catalog and deletes their MinIO warehouse paths before recreating them.
Use it only for pre-production silver data.
"""

from __future__ import annotations

import argparse
import os
import sys
from contextlib import suppress
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from infra.scripts.create_bronze_tables import ensure_namespace, load_local_iceberg_catalog
from lakehouse.schemas.silver_pitch_events import (
    SILVER_PITCH_EVENTS_IDENTIFIER,
    SILVER_PITCH_EVENTS_LOCATION,
    SILVER_PITCH_EVENTS_NAMESPACE,
    SILVER_PITCH_EVENTS_PARTITION_SPEC,
    SILVER_PITCH_EVENTS_SCHEMA,
)
from lakehouse.schemas.silver_pitcher_game_fatigue import (
    SILVER_PITCHER_GAME_FATIGUE_IDENTIFIER,
    SILVER_PITCHER_GAME_FATIGUE_LOCATION,
    SILVER_PITCHER_GAME_FATIGUE_NAMESPACE,
    SILVER_PITCHER_GAME_FATIGUE_PARTITION_SPEC,
    SILVER_PITCHER_GAME_FATIGUE_SCHEMA,
)

TableDefinition = tuple[str, str, str, Any, Any]

SILVER_TABLES: tuple[TableDefinition, ...] = (
    (
        SILVER_PITCH_EVENTS_IDENTIFIER,
        SILVER_PITCH_EVENTS_NAMESPACE,
        SILVER_PITCH_EVENTS_LOCATION,
        SILVER_PITCH_EVENTS_SCHEMA,
        SILVER_PITCH_EVENTS_PARTITION_SPEC,
    ),
    (
        SILVER_PITCHER_GAME_FATIGUE_IDENTIFIER,
        SILVER_PITCHER_GAME_FATIGUE_NAMESPACE,
        SILVER_PITCHER_GAME_FATIGUE_LOCATION,
        SILVER_PITCHER_GAME_FATIGUE_SCHEMA,
        SILVER_PITCHER_GAME_FATIGUE_PARTITION_SPEC,
    ),
)


def _delete_s3_path(location: str) -> None:
    """Delete local MinIO data files for a table location."""
    import s3fs

    fs = s3fs.S3FileSystem(
        key=os.getenv("S3_ACCESS_KEY", "minioadmin"),
        secret=os.getenv("S3_SECRET_KEY", "minioadmin"),
        client_kwargs={
            "endpoint_url": os.getenv("S3_ENDPOINT", "http://localhost:9000"),
            "region_name": os.getenv("AWS_REGION", "us-east-1"),
        },
    )
    path = location.removeprefix("s3://")
    if fs.exists(path):
        fs.rm(path, recursive=True)


def ensure_silver_tables() -> list[Any]:
    """Create silver tables if needed and return the loaded tables."""
    catalog = load_local_iceberg_catalog()
    tables: list[Any] = []

    for identifier, namespace, location, schema, partition_spec in SILVER_TABLES:
        ensure_namespace(catalog, namespace)
        try:
            table = catalog.load_table(identifier)
        except Exception:
            table = catalog.create_table(
                identifier=identifier,
                schema=schema,
                location=location,
                partition_spec=partition_spec,
            )
        print(f"ok: {identifier} at {location}")
        tables.append(table)

    return tables


def recreate_silver_tables() -> list[Any]:
    """Destructively drop, delete, and recreate pre-production silver tables."""
    catalog = load_local_iceberg_catalog()

    for identifier, _, location, _, _ in SILVER_TABLES:
        with suppress(Exception):
            catalog.drop_table(identifier)
        _delete_s3_path(location)

    return ensure_silver_tables()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Destructively drop and recreate pre-production silver tables.",
    )
    args = parser.parse_args()

    if args.recreate:
        recreate_silver_tables()
    else:
        ensure_silver_tables()


if __name__ == "__main__":
    main()
