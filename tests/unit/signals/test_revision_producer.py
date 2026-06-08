"""Unit tests for signals.revision_producer.

Exercise the producer's logic without touching real Kafka. The tests
use an in-memory DuckDB and a fake publisher that records each
publish call for assertion.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest

from ingestion.replay_engine.events import MatchupRevisionEvent
from signals.revision_producer import (
    DEFAULT_TOPIC,
    run_producer,
)


class FakePublisher:
    """Records publish() calls for test assertions."""

    def __init__(self) -> None:
        self.published: list[tuple[str, str, MatchupRevisionEvent]] = []
        self.flushed = False

    def publish(self, *, topic: str, key: str, event: MatchupRevisionEvent) -> None:
        self.published.append((topic, key, event))

    def flush(self, timeout: float = 10.0) -> int:
        self.flushed = True
        return 0


@pytest.fixture
def duckdb_with_signals(tmp_path: Path) -> Path:
    """Create a temporary DuckDB pre-loaded with silver_matchup_signals."""
    db_path = tmp_path / "test.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("CREATE SCHEMA silver")
    con.execute(
        """
        CREATE TABLE silver.silver_matchup_signals (
            event_time TIMESTAMP,
            game_pk BIGINT,
            at_bat_number INTEGER,
            pitch_number INTEGER,
            pitcher_id BIGINT,
            batter_id BIGINT,
            handedness_matchup VARCHAR,
            signal_value DOUBLE,
            confidence_band VARCHAR,
            lineup_state_at_emission VARCHAR
        )
        """
    )
    con.close()
    return db_path


def _insert_signal(
    db_path: Path,
    *,
    game_pk: int = 745000,
    at_bat_number: int = 1,
    pitch_number: int = 1,
    event_time: datetime | None = None,
    signal_value: float = 0.05,
    confidence_band: str = "full",
    lineup_state: str = "confirmed",
    handedness_matchup: str = "R_vs_R",
    pitcher_id: int = 600000,
    batter_id: int = 600100,
) -> None:
    con = duckdb.connect(str(db_path))
    con.execute(
        "INSERT INTO silver.silver_matchup_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            event_time or datetime(2024, 4, 15, 19, 0, 0, tzinfo=UTC),
            game_pk,
            at_bat_number,
            pitch_number,
            pitcher_id,
            batter_id,
            handedness_matchup,
            signal_value,
            confidence_band,
            lineup_state,
        ],
    )
    con.close()


class TestEmptySignals:
    def test_no_signals_yields_zero_revisions(self, duckdb_with_signals: Path) -> None:
        publisher = FakePublisher()
        stats = run_producer(
            duckdb_path=duckdb_with_signals,
            publisher=publisher,
            dry_run=False,
        )
        assert stats.signals_read == 0
        assert stats.revisions_emitted == 0
        assert stats.new_watermark is None
        assert publisher.published == []


class TestSingleSignalPerKey:
    def test_one_signal_per_pitch_yields_no_revisions(self, duckdb_with_signals: Path) -> None:
        # 3 different pitches, one emission each. No pairs.
        for n in range(1, 4):
            _insert_signal(
                duckdb_with_signals,
                game_pk=745000,
                at_bat_number=1,
                pitch_number=n,
            )

        publisher = FakePublisher()
        stats = run_producer(
            duckdb_path=duckdb_with_signals,
            publisher=publisher,
            dry_run=False,
        )
        assert stats.signals_read == 3
        assert stats.groups_processed == 3
        assert stats.revisions_emitted == 0
        assert publisher.published == []


class TestMaterialUpdate:
    def test_value_change_emits_revision(self, duckdb_with_signals: Path) -> None:
        # Same pitch, two emissions, value changed.
        _insert_signal(
            duckdb_with_signals,
            event_time=datetime(2024, 4, 15, 19, 0, 0, tzinfo=UTC),
            signal_value=-0.10,
            confidence_band="reduced",
            lineup_state="projected",
        )
        _insert_signal(
            duckdb_with_signals,
            event_time=datetime(2024, 4, 15, 19, 5, 0, tzinfo=UTC),
            signal_value=0.05,
            confidence_band="full",
            lineup_state="confirmed",
        )

        publisher = FakePublisher()
        stats = run_producer(
            duckdb_path=duckdb_with_signals,
            publisher=publisher,
            dry_run=False,
        )
        assert stats.signals_read == 2
        assert stats.revisions_emitted == 1
        assert len(publisher.published) == 1

        topic, key, event = publisher.published[0]
        assert topic == DEFAULT_TOPIC
        assert key == "745000:1:1"
        assert event.revision_type == "material_update"
        assert event.previous_signal_value == -0.10
        assert event.current_signal_value == 0.05


class TestBaselineConfirmed:
    def test_confidence_rise_with_same_value_emits_revision(
        self, duckdb_with_signals: Path
    ) -> None:
        _insert_signal(
            duckdb_with_signals,
            event_time=datetime(2024, 4, 15, 19, 0, 0, tzinfo=UTC),
            signal_value=0.05,
            confidence_band="reduced",
        )
        _insert_signal(
            duckdb_with_signals,
            event_time=datetime(2024, 4, 15, 19, 5, 0, tzinfo=UTC),
            signal_value=0.05,
            confidence_band="full",
        )

        publisher = FakePublisher()
        stats = run_producer(
            duckdb_path=duckdb_with_signals,
            publisher=publisher,
            dry_run=False,
        )
        assert stats.revisions_emitted == 1
        _, _, event = publisher.published[0]
        assert event.revision_type == "baseline_confirmed"


class TestIdempotency:
    def test_second_run_emits_zero(self, duckdb_with_signals: Path) -> None:
        # Insert a pair, run, then re-run.
        _insert_signal(
            duckdb_with_signals,
            event_time=datetime(2024, 4, 15, 19, 0, 0, tzinfo=UTC),
            signal_value=-0.10,
            confidence_band="reduced",
        )
        _insert_signal(
            duckdb_with_signals,
            event_time=datetime(2024, 4, 15, 19, 5, 0, tzinfo=UTC),
            signal_value=0.05,
            confidence_band="full",
        )

        first = run_producer(
            duckdb_path=duckdb_with_signals,
            publisher=FakePublisher(),
            dry_run=False,
        )
        assert first.revisions_emitted == 1
        assert first.new_watermark == (745000, 1, 1)

        # Second run, no new signals.
        second_publisher = FakePublisher()
        second = run_producer(
            duckdb_path=duckdb_with_signals,
            publisher=second_publisher,
            dry_run=False,
        )
        assert second.signals_read == 0
        assert second.revisions_emitted == 0
        assert second_publisher.published == []


class TestDryRun:
    def test_dry_run_does_not_publish_or_update_watermark(self, duckdb_with_signals: Path) -> None:
        _insert_signal(
            duckdb_with_signals,
            event_time=datetime(2024, 4, 15, 19, 0, 0, tzinfo=UTC),
            signal_value=-0.10,
            confidence_band="reduced",
        )
        _insert_signal(
            duckdb_with_signals,
            event_time=datetime(2024, 4, 15, 19, 5, 0, tzinfo=UTC),
            signal_value=0.05,
            confidence_band="full",
        )

        publisher = FakePublisher()
        stats = run_producer(
            duckdb_path=duckdb_with_signals,
            publisher=publisher,
            dry_run=True,
        )
        assert stats.revisions_emitted == 1  # counted as if emitted
        assert publisher.published == []  # but not actually published
        assert stats.new_watermark is None  # watermark not updated

        # Confirm watermark table is empty / no row written.
        con = duckdb.connect(str(duckdb_with_signals))
        rows = con.execute(
            "SELECT COUNT(*) FROM producer_state.matchup_revision_watermark"
        ).fetchone()
        con.close()
        assert rows[0] == 0


class TestMultipleGroups:
    def test_revisions_across_multiple_natural_keys(self, duckdb_with_signals: Path) -> None:
        # Two pitches, each with two emissions.
        for pitch_number in (1, 2):
            _insert_signal(
                duckdb_with_signals,
                pitch_number=pitch_number,
                event_time=datetime(2024, 4, 15, 19, 0, 0, tzinfo=UTC),
                signal_value=-0.10,
                confidence_band="reduced",
            )
            _insert_signal(
                duckdb_with_signals,
                pitch_number=pitch_number,
                event_time=datetime(2024, 4, 15, 19, 5, 0, tzinfo=UTC),
                signal_value=0.05,
                confidence_band="full",
            )

        publisher = FakePublisher()
        stats = run_producer(
            duckdb_path=duckdb_with_signals,
            publisher=publisher,
            dry_run=False,
        )
        assert stats.signals_read == 4
        assert stats.groups_processed == 2
        assert stats.revisions_emitted == 2
        assert {k for _, k, _ in publisher.published} == {"745000:1:1", "745000:1:2"}
