"""Publish dbt-produced silver models into local Iceberg tables.

dbt owns model SQL in the local DuckDB database. PyIceberg owns the Iceberg
catalog state. This script copies selected dbt model outputs into the matching
local Iceberg silver tables after dbt has completed successfully.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import NamedTuple

import duckdb
import pyarrow as pa

from infra.scripts.create_bronze_tables import load_local_iceberg_catalog
from infra.scripts.create_silver_tables import ensure_silver_tables


class PublishTarget(NamedTuple):
    model_name: str
    duckdb_relation: str
    iceberg_identifier: str
    columns: tuple[str, ...]


PITCH_EVENTS_COLUMNS = (
    "event_time",
    "event_day",
    "game_pk",
    "at_bat_number",
    "pitch_number",
    "inning",
    "inning_topbot",
    "pitcher_id",
    "batter_id",
    "pitch_type",
    "release_speed",
    "release_spin_rate",
    "plate_x",
    "plate_z",
    "zone",
    "balls",
    "strikes",
    "outs_when_up",
    "on_1b",
    "on_2b",
    "on_3b",
    "home_score",
    "away_score",
    "description",
    "events",
    "is_late_arrival",
    "is_duplicate",
    "correction_of",
    "ingestion_time",
    "kafka_partition",
    "source_offset",
)

TARGETS = {
    "silver_pitch_events": PublishTarget(
        model_name="silver_pitch_events",
        duckdb_relation="silver.silver_pitch_events",
        iceberg_identifier="silver.pitch_events",
        columns=PITCH_EVENTS_COLUMNS,
    )
}


def _dbt_database_path() -> Path:
    return Path(os.getenv("DBT_DUCKDB_PATH", "~/.bullpen/dbt.duckdb")).expanduser()


def _normalized_selectors(values: list[str]) -> set[str]:
    selectors: set[str] = set()
    for value in values:
        for token in value.split():
            selectors.add(token.strip("+"))
    return selectors


def _selected_targets(selectors: set[str]) -> list[PublishTarget]:
    if not selectors:
        return list(TARGETS.values())

    return [
        target
        for model_name, target in TARGETS.items()
        if model_name in selectors or f"model.bullpen_signal.{model_name}" in selectors
    ]


def _duckdb_table_exists(conn: duckdb.DuckDBPyConnection, relation: str) -> bool:
    schema, table = relation.split(".", maxsplit=1)
    rows = conn.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_schema = ?
          AND table_name = ?
        """,
        [schema, table],
    ).fetchone()
    return bool(rows and rows[0] > 0)


def _arrow_for_target(conn: duckdb.DuckDBPyConnection, target: PublishTarget) -> pa.Table:
    quoted_columns = ", ".join(f'"{column}"' for column in target.columns)
    return conn.execute(
        f"SELECT {quoted_columns} FROM {target.duckdb_relation}"
    ).fetch_arrow_table()


def publish_targets(targets: list[PublishTarget]) -> None:
    if not targets:
        print("ok: no selected silver dbt models require Iceberg publishing")
        return

    ensure_silver_tables()
    catalog = load_local_iceberg_catalog()

    conn = duckdb.connect(str(_dbt_database_path()), read_only=True)
    try:
        for target in targets:
            if not _duckdb_table_exists(conn, target.duckdb_relation):
                raise RuntimeError(
                    f"dbt relation {target.duckdb_relation} does not exist; "
                    f"run dbt for {target.model_name} before publishing"
                )

            arrow_table = _arrow_for_target(conn, target)
            iceberg_table = catalog.load_table(target.iceberg_identifier)
            iceberg_table.overwrite(
                arrow_table,
                snapshot_properties={"bullpen.source": "dbt"},
            )
            print(
                "ok: published "
                f"{target.model_name} rows={arrow_table.num_rows} "
                f"to {target.iceberg_identifier}"
            )
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("-s", "--select", action="append", default=[])
    args, _ = parser.parse_known_args()

    selectors = _normalized_selectors(args.select)
    publish_targets(_selected_targets(selectors))


if __name__ == "__main__":
    main()
