"""Unit tests for the Avro publisher's Pydantic-to-dict conversion logic.

The serialization itself is exercised end-to-end by the integration test
in tests/integration/test_replay_to_kafka.py (activated in M1 Day 1
Commit 4). These tests focus on the converter functions because they
encode the contract between the Pydantic models and the .avsc files —
if a field is added to one and not the other, these tests catch it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ingestion.replay_engine.avro_publisher import (
    _datetime_to_millis,
    correction_event_to_avro_dict,
    game_state_event_to_avro_dict,
    pitch_event_to_avro_dict,
)
from ingestion.replay_engine.events import (
    CorrectionEvent,
    GameStateEvent,
    PitchEvent,
)


def _make_pitch(**overrides) -> PitchEvent:
    """Build a PitchEvent with sensible defaults; tests override only what they care about."""
    base = {
        "event_time": datetime(2024, 7, 4, 19, 30, 0, tzinfo=UTC),
        "ingest_time": datetime(2024, 7, 4, 19, 30, 0, 500000, tzinfo=UTC),
        "game_pk": 745123,
        "at_bat_number": 12,
        "pitch_number": 3,
        "inning": 5,
        "inning_topbot": "Top",
        "pitcher_id": 605400,
        "batter_id": 660271,
        "pitch_type": "FF",
        "release_speed": 95.4,
        "release_spin_rate": 2400.0,
        "plate_x": 0.12,
        "plate_z": 2.5,
        "zone": 5,
        "balls": 1,
        "strikes": 2,
        "outs_when_up": 1,
        "on_1b": None,
        "on_2b": 660271,
        "on_3b": None,
        "description": "swinging_strike",
        "events": None,
        "home_score": 3,
        "away_score": 2,
    }
    base.update(overrides)
    return PitchEvent(**base)


class TestDatetimeToMillis:
    def test_utc_datetime_converts_to_millis_since_epoch(self) -> None:
        dt = datetime(2024, 7, 4, 19, 30, 0, tzinfo=UTC)
        assert _datetime_to_millis(dt) == 1720121400 * 1000

    def test_microseconds_are_truncated_to_millis(self) -> None:
        dt = datetime(2024, 7, 4, 19, 30, 0, 500000, tzinfo=UTC)
        assert _datetime_to_millis(dt) == 1720121400 * 1000 + 500


class TestPitchEventConversion:
    def test_all_avsc_fields_are_present(self) -> None:
        avsc_fields = {
            "event_time",
            "ingest_time",
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
            "description",
            "events",
            "home_score",
            "away_score",
            "is_late_arrival",
            "is_duplicate",
            "correction_of",
        }
        result = pitch_event_to_avro_dict(_make_pitch())
        assert set(result.keys()) == avsc_fields

    def test_datetime_fields_become_millis(self) -> None:
        pitch = _make_pitch()
        result = pitch_event_to_avro_dict(pitch)
        assert isinstance(result["event_time"], int)
        assert isinstance(result["ingest_time"], int)

    def test_none_optional_fields_pass_through_as_none(self) -> None:
        pitch = _make_pitch(pitch_type=None, release_speed=None, on_1b=None)
        result = pitch_event_to_avro_dict(pitch)
        assert result["pitch_type"] is None
        assert result["release_speed"] is None
        assert result["on_1b"] is None

    def test_inning_topbot_passes_through_as_string_for_avro_field(self) -> None:
        pitch = _make_pitch(inning_topbot="Bot")
        result = pitch_event_to_avro_dict(pitch)
        assert result["inning_topbot"] == "Bot"


class TestGameStateEventConversion:
    def test_all_avsc_fields_are_present(self) -> None:
        gs = GameStateEvent(
            event_time=datetime(2024, 7, 4, 19, 0, 0, tzinfo=UTC),
            ingest_time=datetime(2024, 7, 4, 19, 0, 0, 100000, tzinfo=UTC),
            game_pk=745123,
            inning=1,
            inning_topbot="Top",
            home_score=0,
            away_score=0,
            home_pitcher_id=605400,
            away_pitcher_id=None,
            next_batter_id=660271,
            event_type="game_start",
        )
        avsc_fields = {
            "event_time",
            "ingest_time",
            "game_pk",
            "inning",
            "inning_topbot",
            "home_score",
            "away_score",
            "home_pitcher_id",
            "away_pitcher_id",
            "next_batter_id",
            "event_type",
        }
        result = game_state_event_to_avro_dict(gs)
        assert set(result.keys()) == avsc_fields


class TestCorrectionEventConversion:
    def test_all_avsc_fields_are_present(self) -> None:
        ce = CorrectionEvent(
            event_time=datetime(2024, 7, 4, 19, 30, 0, tzinfo=UTC),
            ingest_time=datetime(2024, 7, 4, 19, 30, 0, 100000, tzinfo=UTC),
            game_pk=745123,
            original_pitch_uid="745123:12:3",
            field="pitch_type",
            old_value="FF",
            new_value="SI",
        )
        avsc_fields = {
            "event_time",
            "ingest_time",
            "game_pk",
            "original_pitch_uid",
            "field",
            "old_value",
            "new_value",
        }
        result = correction_event_to_avro_dict(ce)
        assert set(result.keys()) == avsc_fields
