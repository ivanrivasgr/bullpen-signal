from __future__ import annotations

from unittest.mock import patch

from infra.scripts import refresh_iceberg_sources


def test_refresh_sources_resolves_bronze_and_streaming() -> None:
    # ADR 0023: the streaming matchup signal table is resolved alongside
    # bronze so the reconciliation can read it.
    def fake_location(identifier: str) -> str:
        return f"s3://warehouse/{identifier.replace('.', '/')}/metadata/test.json"

    with (
        patch.object(
            refresh_iceberg_sources, "_table_metadata_location", side_effect=fake_location
        ),
        patch.object(refresh_iceberg_sources, "OUTPUT_PATH") as mock_path,
    ):
        sources = refresh_iceberg_sources.refresh_sources()

    assert set(sources) == {"bronze.pitches", "streaming.matchup_signals"}
    assert (
        sources["streaming.matchup_signals"]["metadata_location"]
        == "s3://warehouse/streaming/matchup_signals/metadata/test.json"
    )
    assert "refreshed_at" in sources["streaming.matchup_signals"]
    mock_path.write_text.assert_called_once()
