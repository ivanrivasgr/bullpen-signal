from __future__ import annotations

import inspect

import pyarrow as pa

from infra.scripts import materialize_dbt_sources


def test_materialize_bronze_pitches_signature_is_explicit() -> None:
    signature = inspect.signature(materialize_dbt_sources.materialize_bronze_pitches)
    assert list(signature.parameters) == [
        "metadata_location",
        "duckdb_path",
        "arrow_table_factory",
    ]


def test_materialize_bronze_pitches_creates_bronze_table(tmp_path) -> None:
    duckdb_path = tmp_path / "dbt.duckdb"
    arrow_table = pa.table(
        {
            "game_pk": [1001, 1002],
            "pitcher_id": [7001, 7002],
        }
    )

    def fake_arrow_table_factory(metadata_location: str) -> pa.Table:
        assert metadata_location == "s3://warehouse/bronze/pitches/metadata/test.json"
        return arrow_table

    rows = materialize_dbt_sources.materialize_bronze_pitches(
        "s3://warehouse/bronze/pitches/metadata/test.json",
        duckdb_path,
        arrow_table_factory=fake_arrow_table_factory,
    )

    assert rows == 2

    import duckdb

    conn = duckdb.connect(str(duckdb_path), read_only=True)
    try:
        result = conn.execute(
            """
            SELECT COUNT(*), SUM(game_pk), SUM(pitcher_id)
            FROM bronze.pitches
            """
        ).fetchone()
    finally:
        conn.close()

    assert result == (2, 2003, 14003)


def test_materialize_iceberg_source_creates_arbitrary_table(tmp_path) -> None:
    # The generic bridge materializes any namespace.table, not just bronze —
    # here the streaming matchup signals table (ADR 0023).
    duckdb_path = tmp_path / "dbt.duckdb"
    arrow_table = pa.table(
        {
            "game_pk": [2001, 2002, 2003],
            "signal_value": [0.05, -0.10, 0.08],
        }
    )

    def fake_arrow_table_factory(metadata_location: str) -> pa.Table:
        assert metadata_location == "s3://warehouse/streaming/matchup_signals/metadata/test.json"
        return arrow_table

    rows = materialize_dbt_sources.materialize_iceberg_source(
        "streaming",
        "matchup_signals",
        "s3://warehouse/streaming/matchup_signals/metadata/test.json",
        duckdb_path,
        arrow_table_factory=fake_arrow_table_factory,
    )
    assert rows == 3

    import duckdb

    conn = duckdb.connect(str(duckdb_path), read_only=True)
    try:
        result = conn.execute(
            "SELECT COUNT(*), SUM(game_pk) FROM streaming.matchup_signals"
        ).fetchone()
    finally:
        conn.close()
    assert result == (3, 6006)


def test_materialize_bronze_pitches_delegates_to_generic(tmp_path) -> None:
    # The bronze wrapper still produces bronze.pitches, now via the generic.
    duckdb_path = tmp_path / "dbt.duckdb"
    arrow_table = pa.table({"game_pk": [9001], "pitcher_id": [3001]})

    rows = materialize_dbt_sources.materialize_bronze_pitches(
        "s3://warehouse/bronze/pitches/metadata/test.json",
        duckdb_path,
        arrow_table_factory=lambda _: arrow_table,
    )
    assert rows == 1

    import duckdb

    conn = duckdb.connect(str(duckdb_path), read_only=True)
    try:
        result = conn.execute("SELECT COUNT(*) FROM bronze.pitches").fetchone()
    finally:
        conn.close()
    assert result == (1,)
