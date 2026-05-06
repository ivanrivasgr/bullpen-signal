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


def materialize_bronze_pitches(
    metadata_location: str,
    duckdb_path: Path | str | None = None,
    *,
    arrow_table_factory: ArrowTableFactory = arrow_table_from_metadata,
) -> int:
    """Materialize bronze.pitches into DuckDB and return the row count."""
    target_path = Path(duckdb_path).expanduser() if duckdb_path else default_dbt_duckdb_path()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    arrow_table = arrow_table_factory(metadata_location)
    conn = duckdb.connect(str(target_path))

    try:
        conn.execute("CREATE SCHEMA IF NOT EXISTS bronze")
        conn.register("_bronze_pitches_arrow", arrow_table)
        conn.execute(
            """
            CREATE OR REPLACE TABLE bronze.pitches AS
            SELECT * FROM _bronze_pitches_arrow
            """
        )
    finally:
        conn.close()

    row_count = arrow_table.num_rows
    print(
        f"materialized: bronze.pitches at {target_path} "
        f"from snapshot {metadata_location} rows={row_count}"
    )
    return row_count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata-location", required=True)
    parser.add_argument("--duckdb-path", type=Path)
    args = parser.parse_args()

    try:
        materialize_bronze_pitches(args.metadata_location, args.duckdb_path)
    except Exception as exc:
        print(f"error: failed to materialize bronze.pitches: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
