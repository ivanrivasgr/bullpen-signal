"""Materialize local Iceberg sources into the dbt DuckDB database.

dbt-duckdb cannot read the local Iceberg catalog reliably (DuckDB iceberg_scan
fails on the bronze.pitches manifest with a DATE -> INTEGER cast error).
Instead, this helper reads the current Iceberg snapshot through PyIceberg and
materializes it as a native DuckDB table. dbt then runs SQL against that table.

This is local-dev scaffolding. Cloud engines (Snowflake, Athena, Redshift) read
Iceberg natively and do not need this step.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Protocol

import duckdb
import pyarrow as pa
from pyiceberg.table import StaticTable

from lakehouse.iceberg_io import iceberg_file_io_properties


class ArrowTableFactory(Protocol):
    def __call__(self, metadata_location: str) -> pa.Table: ...


def default_dbt_duckdb_path() -> Path:
    """Return the local dbt DuckDB path."""
    return Path(os.getenv("BULLPEN_DBT_DUCKDB_PATH", "~/.bullpen/dbt.duckdb")).expanduser()


def arrow_table_from_metadata(metadata_location: str) -> pa.Table:
    """Read an Iceberg snapshot metadata file into an Arrow table."""
    table = StaticTable.from_metadata(
        metadata_location,
        properties=iceberg_file_io_properties(),
    )
    return table.scan().to_arrow()


def materialize_iceberg_source(
    namespace: str,
    table: str,
    metadata_location: str,
    duckdb_path: Path | str | None = None,
    *,
    arrow_table_factory: ArrowTableFactory = arrow_table_from_metadata,
) -> int:
    """Materialize an Iceberg snapshot into DuckDB as namespace.table.

    Reads the current snapshot through PyIceberg (via arrow_table_factory)
    and writes it as a native DuckDB table the dbt sources resolve against.
    Generic over the source so the bridge serves bronze.pitches and the
    streaming matchup signals table alike (ADR 0023), rather than hardcoding
    a single table. Returns the row count.
    """
    target_path = Path(duckdb_path).expanduser() if duckdb_path else default_dbt_duckdb_path()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    arrow_table = arrow_table_factory(metadata_location)
    register_name = f"_{namespace}_{table}_arrow"
    conn = duckdb.connect(str(target_path))
    try:
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {namespace}")
        conn.register(register_name, arrow_table)
        conn.execute(
            f"CREATE OR REPLACE TABLE {namespace}.{table} AS SELECT * FROM {register_name}"
        )
    finally:
        conn.close()
    row_count = arrow_table.num_rows
    print(
        f"materialized: {namespace}.{table} at {target_path} "
        f"from snapshot {metadata_location} rows={row_count}"
    )
    return row_count


def materialize_bronze_pitches(
    metadata_location: str,
    duckdb_path: Path | str | None = None,
    *,
    arrow_table_factory: ArrowTableFactory = arrow_table_from_metadata,
) -> int:
    """Materialize bronze.pitches into DuckDB and return the row count.

    Thin wrapper over materialize_iceberg_source preserved for the existing
    callers; bronze.pitches is just one source the generic bridge handles.
    """
    return materialize_iceberg_source(
        "bronze",
        "pitches",
        metadata_location,
        duckdb_path,
        arrow_table_factory=arrow_table_factory,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata-location", required=True)
    parser.add_argument("--duckdb-path", type=Path)
    # Default to bronze.pitches so existing callers that pass only
    # --metadata-location keep materializing it; pass --namespace/--table to
    # materialize another Iceberg source, e.g. streaming.matchup_signals.
    parser.add_argument("--namespace", default="bronze")
    parser.add_argument("--table", default="pitches")
    args = parser.parse_args()
    identifier = f"{args.namespace}.{args.table}"
    try:
        materialize_iceberg_source(
            args.namespace,
            args.table,
            args.metadata_location,
            args.duckdb_path,
        )
    except Exception as exc:
        print(f"error: failed to materialize {identifier}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
