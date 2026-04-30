"""Create local Iceberg bronze tables for development.

The --recreate option is destructive: it drops bronze.pitches from the local
Iceberg catalog and deletes the MinIO warehouse path before recreating the
table. Use it only for pre-production bronze smoke data.
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

from pyiceberg.catalog import load_catalog

from lakehouse.schemas.bronze_pitches import (
    BRONZE_PITCHES_IDENTIFIER,
    BRONZE_PITCHES_LOCATION,
    BRONZE_PITCHES_NAMESPACE,
    BRONZE_PITCHES_PARTITION_SPEC,
    BRONZE_PITCHES_SCHEMA,
)


def _catalog_properties() -> dict[str, str]:
    return {
        "type": "rest",
        "uri": os.getenv("ICEBERG_REST_URI", "http://localhost:8181"),
        "warehouse": os.getenv("ICEBERG_WAREHOUSE", "s3://bullpen-warehouse/"),
        "s3.endpoint": os.getenv("S3_ENDPOINT", "http://localhost:9000"),
        "s3.access-key-id": os.getenv("S3_ACCESS_KEY", "minioadmin"),
        "s3.secret-access-key": os.getenv("S3_SECRET_KEY", "minioadmin"),
        "s3.region": os.getenv("AWS_REGION", "us-east-1"),
        "s3.path-style-access": "true",
    }


def load_local_iceberg_catalog() -> Any:
    """Load the local REST Iceberg catalog used by the dev stack."""
    return load_catalog("bullpen", **_catalog_properties())


def ensure_namespace(catalog: Any, namespace: str) -> None:
    """Create an Iceberg namespace if it does not already exist."""
    with suppress(Exception):
        catalog.create_namespace(namespace)


def ensure_bronze_pitches_table() -> Any:
    """Create bronze.pitches if needed and return the loaded table."""
    catalog = load_local_iceberg_catalog()
    ensure_namespace(catalog, BRONZE_PITCHES_NAMESPACE)

    try:
        table = catalog.load_table(BRONZE_PITCHES_IDENTIFIER)
    except Exception:
        table = catalog.create_table(
            identifier=BRONZE_PITCHES_IDENTIFIER,
            schema=BRONZE_PITCHES_SCHEMA,
            location=BRONZE_PITCHES_LOCATION,
            partition_spec=BRONZE_PITCHES_PARTITION_SPEC,
        )

    print(f"ok: {BRONZE_PITCHES_IDENTIFIER} at {BRONZE_PITCHES_LOCATION}")
    return table


def _delete_bronze_pitches_path() -> None:
    """Delete local MinIO data files for bronze.pitches."""
    import s3fs

    fs = s3fs.S3FileSystem(
        key=os.getenv("S3_ACCESS_KEY", "minioadmin"),
        secret=os.getenv("S3_SECRET_KEY", "minioadmin"),
        client_kwargs={
            "endpoint_url": os.getenv("S3_ENDPOINT", "http://localhost:9000"),
            "region_name": os.getenv("AWS_REGION", "us-east-1"),
        },
    )
    path = BRONZE_PITCHES_LOCATION.removeprefix("s3://")
    if fs.exists(path):
        fs.rm(path, recursive=True)


def recreate_bronze_pitches_table() -> Any:
    """Destructively drop, delete, and recreate pre-production bronze.pitches."""
    catalog = load_local_iceberg_catalog()
    with suppress(Exception):
        catalog.drop_table(BRONZE_PITCHES_IDENTIFIER)

    _delete_bronze_pitches_path()
    return ensure_bronze_pitches_table()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Destructively drop and recreate bronze.pitches pre-production data.",
    )
    args = parser.parse_args()

    if args.recreate:
        recreate_bronze_pitches_table()
    else:
        ensure_bronze_pitches_table()


if __name__ == "__main__":
    main()
