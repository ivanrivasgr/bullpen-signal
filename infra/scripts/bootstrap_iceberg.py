"""Idempotent Iceberg schema bootstrap for Bullpen Signal lakehouse.

Creates the three Medallion architecture namespaces:
  - bronze : raw ingestion (pitches, game_state, corrections, alerts)
  - silver : cleaned + conformed dimensions
  - gold   : business-level aggregations (pitcher game logs, season stats)

Namespaces map 1:1 to dbt project layers. Tables within each namespace
are created lazily by Flink jobs (bronze) or dbt models (silver/gold),
not by this script. This keeps table schemas as code next to their
producers, not centralized in an infra script.

Run once after `make up`. Safe to re-run (idempotent).

Usage:
    python infra/scripts/bootstrap_iceberg.py

Environment variables (optional, defaults shown):
    ICEBERG_CATALOG_URI      = http://localhost:8181
    S3_ENDPOINT              = http://localhost:9000
    S3_ACCESS_KEY            = minioadmin
    S3_SECRET_KEY            = minioadmin
"""

from __future__ import annotations

import os
import sys

from pyiceberg.catalog import load_catalog
from pyiceberg.exceptions import NamespaceAlreadyExistsError

NAMESPACES: list[tuple[str, str]] = [
    ("bronze", "Raw ingestion from Kafka topics via Flink streaming"),
    ("silver", "Cleaned, deduplicated, and conformed dimensions"),
    ("gold", "Business-level aggregations for dashboards and ML features"),
]


def main() -> int:
    catalog_uri = os.getenv("ICEBERG_CATALOG_URI", "http://localhost:8181")
    s3_endpoint = os.getenv("S3_ENDPOINT", "http://localhost:9000")
    s3_access_key = os.getenv("S3_ACCESS_KEY", "minioadmin")
    s3_secret_key = os.getenv("S3_SECRET_KEY", "minioadmin")

    print(f"Loading Iceberg REST catalog at {catalog_uri}")
    catalog = load_catalog(
        "bullpen",
        **{
            "type": "rest",
            "uri": catalog_uri,
            "s3.endpoint": s3_endpoint,
            "s3.access-key-id": s3_access_key,
            "s3.secret-access-key": s3_secret_key,
        },
    )

    created: list[str] = []
    existing: list[str] = []

    for ns, description in NAMESPACES:
        try:
            catalog.create_namespace(ns, properties={"comment": description})
            created.append(ns)
            print(f"  + created namespace: {ns}")
        except NamespaceAlreadyExistsError:
            existing.append(ns)
            print(f"  = namespace exists: {ns}")

    print()
    print(f"Summary: {len(created)} created, {len(existing)} already existed")
    print()

    # List current state for verification
    print("Current namespaces in catalog 'bullpen':")
    for ns in catalog.list_namespaces():
        print(f"  - {'.'.join(ns)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
