from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from lakehouse import query


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self) -> bytes:
        return json.dumps(
            {"metadata-location": ("s3://bullpen-warehouse/bronze/pitches/metadata/00000.json")}
        ).encode("utf-8")


def test_sql_literal_escapes_single_quotes() -> None:
    assert query._sql_literal("a'b") == "'a''b'"


def test_view_name_for_identifier_replaces_namespace_dot() -> None:
    assert query._view_name_for_identifier("bronze.pitches") == "bronze_pitches"


def test_table_metadata_location_reads_iceberg_rest_response() -> None:
    with patch("urllib.request.urlopen", return_value=_FakeResponse()) as urlopen:
        location = query.table_metadata_location("bronze.pitches")

    assert location.endswith("00000.json")
    urlopen.assert_called_once()


def test_connection_registers_default_bronze_view() -> None:
    fake_conn = MagicMock()
    fake_arrow = MagicMock()

    with (
        patch("duckdb.connect", return_value=fake_conn),
        patch("lakehouse.query._arrow_table_for_identifier", return_value=fake_arrow),
    ):
        conn = query.connection()

    assert conn is fake_conn
    fake_conn.register.assert_called_once_with("bronze_pitches", fake_arrow)


def test_query_snapshot_registers_static_metadata_view() -> None:
    fake_conn = MagicMock()
    fake_arrow = MagicMock()

    with (
        patch("duckdb.connect", return_value=fake_conn),
        patch("lakehouse.query._arrow_table_for_metadata", return_value=fake_arrow),
    ):
        query.query_snapshot(
            "SELECT COUNT(*) FROM bronze_pitches",
            metadata_location="s3://bucket/table/metadata.json",
        )

    fake_conn.register.assert_called_once_with("bronze_pitches", fake_arrow)
    fake_conn.execute.assert_called_once_with("SELECT COUNT(*) FROM bronze_pitches")


def test_count_rows_queries_identifier_as_registered_view() -> None:
    with patch("lakehouse.query.query", return_value=[(7,)]) as run_query:
        assert query.count_rows("bronze.pitches", where="game_pk = 1") == 7

    run_query.assert_called_once_with(
        "SELECT COUNT(*) FROM bronze_pitches WHERE game_pk = 1",
        view_map={"bronze_pitches": "bronze.pitches"},
    )
