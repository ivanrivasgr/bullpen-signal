"""Create local Iceberg bronze tables idempotently."""

from __future__ import annotations

import os
from contextlib import suppress

from pyiceberg.catalog import load_catalog

from lakehouse.schemas.bronze_pitches import (
    BRONZE_PITCHES_IDENTIFIER,
    BRONZE_PITCHES_LOCATION,
    BRONZE_PITCHES_PARTITION_SPEC,
    BRONZE_PITCHES_PROPERTIES,
    BRONZE_PITCHES_SCHEMA,
    bronze_pitches_field_names,
)


def load_local_iceberg_catalog():
    return load_catalog(
        os.getenv("ICEBERG_CATALOG_NAME", "bullpen"),
        **{
            "type": "rest",
            "uri": os.getenv("ICEBERG_REST_URI", "http://localhost:8181"),
            "warehouse": os.getenv("ICEBERG_WAREHOUSE", "s3://bullpen-warehouse/"),
            "s3.endpoint": os.getenv("S3_ENDPOINT", "http://localhost:9000"),
            "s3.access-key-id": os.getenv("S3_ACCESS_KEY", "minioadmin"),
            "s3.secret-access-key": os.getenv("S3_SECRET_KEY", "minioadmin"),
            "s3.region": os.getenv("S3_REGION", "us-east-1"),
            "s3.path-style-access": "true",
        },
    )


def ensure_namespace(catalog, namespace: str = "bronze") -> None:
    # Namespace already exists in the normal local stack bootstrap path.
    with suppress(Exception):
        catalog.create_namespace(namespace)


def ensure_bronze_pitches_table():
    catalog = load_local_iceberg_catalog()
    ensure_namespace(catalog, "bronze")

    table = catalog.create_table_if_not_exists(
        identifier=BRONZE_PITCHES_IDENTIFIER,
        schema=BRONZE_PITCHES_SCHEMA,
        location=BRONZE_PITCHES_LOCATION,
        partition_spec=BRONZE_PITCHES_PARTITION_SPEC,
        properties=BRONZE_PITCHES_PROPERTIES,
    )

    table_fields = {field.name for field in table.schema().fields}
    expected = set(bronze_pitches_field_names())
    missing = sorted(expected - table_fields)
    if missing:
        raise RuntimeError(f"{BRONZE_PITCHES_IDENTIFIER} exists but is missing fields: {missing}")

    return table


def main() -> None:
    table = ensure_bronze_pitches_table()
    print(f"ok: {BRONZE_PITCHES_IDENTIFIER} at {table.location()}")


if __name__ == "__main__":
    main()
