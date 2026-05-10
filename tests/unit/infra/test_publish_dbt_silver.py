"""Unit tests for infra/scripts/publish_dbt_silver.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pyarrow as pa
import pytest

from infra.scripts.publish_dbt_silver import _verify_and_cast, publish_table


def _make_iceberg_mock(fields: list[tuple[str, pa.DataType]]) -> MagicMock:
    """Return a mock iceberg Table whose schema maps to the given Arrow fields."""
    arrow_schema = pa.schema([pa.field(name, dtype) for name, dtype in fields])
    iceberg_table = MagicMock()
    iceberg_table.current_snapshot.return_value = MagicMock(snapshot_id=42)

    with patch("infra.scripts.publish_dbt_silver.schema_to_pyarrow", return_value=arrow_schema):
        yield iceberg_table, arrow_schema


# ──────────────────────────────────────────────────────
# _verify_and_cast
# ──────────────────────────────────────────────────────


def test_verify_and_cast_passes_with_matching_schema() -> None:
    arrow_in = pa.table(
        {"game_pk": pa.array([1], type=pa.int64()), "pitch_count": pa.array([5], type=pa.int32())}
    )
    expected_schema = pa.schema(
        [pa.field("game_pk", pa.int64()), pa.field("pitch_count", pa.int32())]
    )
    iceberg_mock = MagicMock()

    with patch("infra.scripts.publish_dbt_silver.schema_to_pyarrow", return_value=expected_schema):
        result = _verify_and_cast(arrow_in, iceberg_mock, "silver.pitch_events")

    assert result.schema.names == ["game_pk", "pitch_count"]
    assert result.num_rows == 1


def test_verify_and_cast_casts_compatible_types() -> None:
    # DuckDB returns int64 for a column the Iceberg schema expects as int32
    arrow_in = pa.table({"game_pk": pa.array([1, 2], type=pa.int64())})
    expected_schema = pa.schema([pa.field("game_pk", pa.int32())])
    iceberg_mock = MagicMock()

    with patch("infra.scripts.publish_dbt_silver.schema_to_pyarrow", return_value=expected_schema):
        result = _verify_and_cast(arrow_in, iceberg_mock, "silver.pitch_events")

    assert result.schema.field("game_pk").type == pa.int32()


def test_verify_and_cast_drops_extra_duckdb_columns() -> None:
    arrow_in = pa.table(
        {
            "game_pk": pa.array([1], type=pa.int64()),
            "extra_column": pa.array(["oops"], type=pa.string()),
        }
    )
    expected_schema = pa.schema([pa.field("game_pk", pa.int64())])
    iceberg_mock = MagicMock()

    with patch("infra.scripts.publish_dbt_silver.schema_to_pyarrow", return_value=expected_schema):
        result = _verify_and_cast(arrow_in, iceberg_mock, "silver.pitch_events")

    assert result.schema.names == ["game_pk"]


def test_verify_and_cast_fails_on_missing_required_column() -> None:
    arrow_in = pa.table({"game_pk": pa.array([1], type=pa.int64())})
    expected_schema = pa.schema(
        [
            pa.field("game_pk", pa.int64()),
            pa.field("pitcher_id", pa.int64()),  # missing from DuckDB
        ]
    )
    iceberg_mock = MagicMock()

    with (
        patch("infra.scripts.publish_dbt_silver.schema_to_pyarrow", return_value=expected_schema),
        pytest.raises(ValueError, match="pitcher_id"),
    ):
        _verify_and_cast(arrow_in, iceberg_mock, "silver.pitch_events")


def test_verify_and_cast_fails_on_incompatible_type() -> None:
    arrow_in = pa.table({"game_pk": pa.array(["not-a-number"], type=pa.string())})
    expected_schema = pa.schema([pa.field("game_pk", pa.int64())])
    iceberg_mock = MagicMock()

    with (
        patch("infra.scripts.publish_dbt_silver.schema_to_pyarrow", return_value=expected_schema),
        pytest.raises(ValueError, match="game_pk"),
    ):
        _verify_and_cast(arrow_in, iceberg_mock, "silver.pitch_events")


# ──────────────────────────────────────────────────────
# publish_table — append vs overwrite
# ──────────────────────────────────────────────────────


def _simple_arrow_table() -> pa.Table:
    return pa.table(
        {"game_pk": pa.array([1], type=pa.int64()), "pitch_count": pa.array([5], type=pa.int32())}
    )


def test_publish_table_calls_append_by_default(tmp_path: Path) -> None:
    db_path = tmp_path / "dbt.duckdb"
    import duckdb

    conn = duckdb.connect(str(db_path))
    conn.execute("CREATE SCHEMA silver")
    conn.execute("CREATE TABLE silver.silver_pitch_events (game_pk BIGINT, pitch_count INTEGER)")
    conn.execute("INSERT INTO silver.silver_pitch_events VALUES (1, 5)")
    conn.close()

    expected_schema = pa.schema(
        [pa.field("game_pk", pa.int64()), pa.field("pitch_count", pa.int32())]
    )
    iceberg_mock = MagicMock()
    iceberg_mock.current_snapshot.return_value = MagicMock(snapshot_id=99)
    catalog_mock = MagicMock()
    catalog_mock.load_table.return_value = iceberg_mock

    with patch("infra.scripts.publish_dbt_silver.schema_to_pyarrow", return_value=expected_schema):
        publish_table(
            iceberg_identifier="silver.pitch_events",
            catalog=catalog_mock,
            duckdb_path=db_path,
            full_refresh=False,
        )

    iceberg_mock.append.assert_called_once()
    iceberg_mock.overwrite.assert_not_called()


def test_publish_table_calls_overwrite_on_full_refresh(tmp_path: Path) -> None:
    db_path = tmp_path / "dbt.duckdb"
    import duckdb

    conn = duckdb.connect(str(db_path))
    conn.execute("CREATE SCHEMA silver")
    conn.execute("CREATE TABLE silver.silver_pitch_events (game_pk BIGINT, pitch_count INTEGER)")
    conn.execute("INSERT INTO silver.silver_pitch_events VALUES (2, 10)")
    conn.close()

    expected_schema = pa.schema(
        [pa.field("game_pk", pa.int64()), pa.field("pitch_count", pa.int32())]
    )
    iceberg_mock = MagicMock()
    iceberg_mock.current_snapshot.return_value = MagicMock(snapshot_id=100)
    catalog_mock = MagicMock()
    catalog_mock.load_table.return_value = iceberg_mock

    with patch("infra.scripts.publish_dbt_silver.schema_to_pyarrow", return_value=expected_schema):
        publish_table(
            iceberg_identifier="silver.pitch_events",
            catalog=catalog_mock,
            duckdb_path=db_path,
            full_refresh=True,
        )

    iceberg_mock.overwrite.assert_called_once()
    iceberg_mock.append.assert_not_called()
