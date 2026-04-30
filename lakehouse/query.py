"""DuckDB helpers for local Iceberg inspection.

PyIceberg owns Iceberg snapshot reads; DuckDB owns SQL over the materialized
Arrow table. This avoids relying on DuckDB's native Iceberg metadata reader for
local MinIO tables while still giving a simple DuckDB query surface.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

import duckdb
import pyarrow as pa
from pyiceberg.table import StaticTable

from infra.scripts.create_bronze_tables import load_local_iceberg_catalog

ICEBERG_REST_URI = "http://localhost:8181"
DEFAULT_VIEW_MAP = {"bronze_pitches": "bronze.pitches"}


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _iceberg_file_io_properties() -> dict[str, str]:
    return {
        "s3.endpoint": os.getenv("S3_ENDPOINT", "http://localhost:9000"),
        "s3.access-key-id": os.getenv("S3_ACCESS_KEY", "minioadmin"),
        "s3.secret-access-key": os.getenv("S3_SECRET_KEY", "minioadmin"),
        "s3.region": os.getenv("S3_REGION", "us-east-1"),
        "s3.path-style-access": "true",
    }


def _view_name_for_identifier(identifier: str) -> str:
    return identifier.replace(".", "_")


def table_metadata_location(
    identifier: str,
    *,
    rest_uri: str = ICEBERG_REST_URI,
) -> str:
    namespace, table = identifier.split(".", maxsplit=1)
    url = f"{rest_uri.rstrip('/')}/v1/namespaces/{namespace}/tables/{table}"

    with urllib.request.urlopen(url, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))

    metadata_location = payload.get("metadata-location") or payload.get("metadataLocation")
    if not metadata_location:
        raise RuntimeError(f"Iceberg REST response did not include metadata location: {payload}")

    return metadata_location


def _arrow_table_for_identifier(identifier: str) -> pa.Table:
    catalog = load_local_iceberg_catalog()
    table = catalog.load_table(identifier)
    return table.scan().to_arrow()


def _arrow_table_for_metadata(metadata_location: str) -> pa.Table:
    table = StaticTable.from_metadata(
        metadata_location,
        properties=_iceberg_file_io_properties(),
    )
    return table.scan().to_arrow()


def connection(
    *,
    database: str = ":memory:",
    register_views: bool = True,
    view_map: dict[str, str] | None = None,
) -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(database)

    try:
        if register_views:
            for view_name, identifier in (view_map or DEFAULT_VIEW_MAP).items():
                conn.register(view_name, _arrow_table_for_identifier(identifier))
    except Exception:
        conn.close()
        raise

    return conn


def query(sql: str, *, view_map: dict[str, str] | None = None) -> list[tuple[Any, ...]]:
    conn = connection(view_map=view_map)

    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def query_df(sql: str, *, view_map: dict[str, str] | None = None):
    conn = connection(view_map=view_map)

    try:
        return conn.execute(sql).df()
    finally:
        conn.close()


def query_snapshot(
    sql: str,
    *,
    metadata_location: str,
    view_name: str = "bronze_pitches",
) -> list[tuple[Any, ...]]:
    conn = duckdb.connect(database=":memory:")

    try:
        conn.register(view_name, _arrow_table_for_metadata(metadata_location))
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def count_rows(identifier: str, *, where: str | None = None) -> int:
    view_name = _view_name_for_identifier(identifier)
    where_sql = f" WHERE {where}" if where else ""
    rows = query(
        f"SELECT COUNT(*) FROM {view_name}{where_sql}",
        view_map={view_name: identifier},
    )
    return int(rows[0][0])
