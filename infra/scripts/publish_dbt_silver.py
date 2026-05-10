"""Publish silver DuckDB outputs to Iceberg via PyIceberg.

Reads silver tables from the local dbt DuckDB database and appends (or
overwrites with --full-refresh) them to the corresponding Iceberg tables in
the REST catalog.

Tables published:
  DuckDB silver.silver_pitch_events       -> Iceberg silver.pitch_events
  DuckDB silver.silver_pitcher_game_fatigue -> Iceberg silver.pitcher_game_fatigue

Schema verification: the script checks that all columns expected by the
Iceberg schema are present in the DuckDB table before writing. Type
mismatches that cannot be cast raise a descriptive error.

Usage:
    python infra/scripts/publish_dbt_silver.py
    python infra/scripts/publish_dbt_silver.py --full-refresh
    python infra/scripts/publish_dbt_silver.py --tables pitch_events
    BULLPEN_SKIP_PUBLISH=1 ./dbt/run.sh  # skip publish in run.sh
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

import duckdb
import pyarrow as pa
from pyiceberg.catalog import load_catalog
from pyiceberg.expressions import AlwaysTrue
from pyiceberg.io.pyarrow import schema_to_pyarrow
from pyiceberg.table import Table

from infra.scripts.materialize_dbt_sources import default_dbt_duckdb_path

ICEBERG_REST_URI = os.getenv("ICEBERG_REST_URI", "http://localhost:8181")

# Map: (dbt DuckDB table) -> Iceberg identifier
SILVER_TABLES: dict[str, str] = {
    "pitch_events": "silver.pitch_events",
    "pitcher_game_fatigue": "silver.pitcher_game_fatigue",
}

# Map: Iceberg identifier -> DuckDB fully-qualified table name
_DUCKDB_TABLE: dict[str, str] = {
    "silver.pitch_events": "silver.silver_pitch_events",
    "silver.pitcher_game_fatigue": "silver.silver_pitcher_game_fatigue",
}


def _catalog_properties() -> dict[str, str]:
    return {
        "type": "rest",
        "uri": ICEBERG_REST_URI,
        "warehouse": os.getenv("ICEBERG_WAREHOUSE", "s3://bullpen-warehouse/"),
        "s3.endpoint": os.getenv("S3_ENDPOINT", "http://localhost:9000"),
        "s3.access-key-id": os.getenv("S3_ACCESS_KEY", "minioadmin"),
        "s3.secret-access-key": os.getenv("S3_SECRET_KEY", "minioadmin"),
        "s3.region": os.getenv("AWS_REGION", "us-east-1"),
        "s3.path-style-access": "true",
    }


def load_iceberg_catalog() -> Any:
    return load_catalog("bullpen", **_catalog_properties())


def read_duckdb_table(duckdb_path: Path, duckdb_table: str) -> pa.Table:
    conn = duckdb.connect(str(duckdb_path), read_only=True)
    try:
        return conn.execute(f"SELECT * FROM {duckdb_table}").to_arrow_table()
    finally:
        conn.close()


def _verify_and_cast(
    arrow_table: pa.Table,
    iceberg_table: Table,
    iceberg_identifier: str,
) -> pa.Table:
    """Verify column coverage and cast DuckDB arrow table to the Iceberg schema.

    Raises ValueError for missing required columns or incompatible types.
    Drops any extra DuckDB columns not present in the Iceberg schema.
    """
    expected_schema = schema_to_pyarrow(iceberg_table.schema())
    actual_names = set(arrow_table.schema.names)
    expected_names = set(expected_schema.names)

    missing = expected_names - actual_names
    if missing:
        raise ValueError(
            f"{iceberg_identifier}: columns present in Iceberg schema but missing "
            f"from DuckDB table: {sorted(missing)}"
        )

    # Select columns in Iceberg order, cast types, and apply the expected schema
    # (including field nullability) so PyIceberg's schema validator accepts the table.
    columns = []
    for field in expected_schema:
        col = arrow_table.column(field.name)
        if col.type != field.type:
            try:
                col = col.cast(field.type)
            except (pa.ArrowInvalid, pa.ArrowNotImplementedError) as exc:
                raise ValueError(
                    f"{iceberg_identifier}: cannot cast '{field.name}' from "
                    f"{col.type} to {field.type}: {exc}"
                ) from exc
        columns.append(col)

    return pa.table(dict(zip(expected_schema.names, columns, strict=False)), schema=expected_schema)


def publish_table(
    *,
    iceberg_identifier: str,
    catalog: Any,
    duckdb_path: Path,
    full_refresh: bool,
) -> int:
    duckdb_table = _DUCKDB_TABLE[iceberg_identifier]
    arrow_table = read_duckdb_table(duckdb_path, duckdb_table)
    iceberg_table = catalog.load_table(iceberg_identifier)
    cast_table = _verify_and_cast(arrow_table, iceberg_table, iceberg_identifier)

    if full_refresh:
        iceberg_table.overwrite(cast_table, overwrite_filter=AlwaysTrue())
        action = "overwritten"
    else:
        iceberg_table.append(cast_table)
        action = "appended"

    snapshot_id = (
        iceberg_table.current_snapshot().snapshot_id if iceberg_table.current_snapshot() else None
    )
    rows = cast_table.num_rows
    print(f"published: {iceberg_identifier} {action} rows={rows} snapshot={snapshot_id}")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish silver DuckDB outputs to Iceberg.")
    parser.add_argument(
        "--tables",
        nargs="+",
        choices=list(SILVER_TABLES),
        default=list(SILVER_TABLES),
        help="Which silver tables to publish (default: all).",
    )
    parser.add_argument(
        "--full-refresh",
        action="store_true",
        help="Overwrite Iceberg table data instead of appending.",
    )
    parser.add_argument(
        "--duckdb-path",
        type=Path,
        default=None,
        help="Path to the local dbt DuckDB file (default: ~/.bullpen/dbt.duckdb).",
    )
    args = parser.parse_args()

    duckdb_path = (
        Path(args.duckdb_path).expanduser() if args.duckdb_path else default_dbt_duckdb_path()
    )

    if not duckdb_path.exists():
        print(f"error: DuckDB file not found at {duckdb_path}", file=sys.stderr)
        return 1

    catalog = load_iceberg_catalog()

    errors: list[str] = []
    for table_key in args.tables:
        iceberg_identifier = SILVER_TABLES[table_key]
        try:
            publish_table(
                iceberg_identifier=iceberg_identifier,
                catalog=catalog,
                duckdb_path=duckdb_path,
                full_refresh=args.full_refresh,
            )
        except Exception as exc:
            msg = f"error: failed to publish {iceberg_identifier}: {exc}"
            print(msg, file=sys.stderr)
            errors.append(msg)

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
