"""Unit tests for the Statcast-row to PitchEvent mapping."""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pandas as pd
import pytest

from ingestion.replay_engine.mapping import row_to_pitch_event


def _base_row() -> pd.Series:
    return pd.Series(
        {
            "event_time": pd.Timestamp("2024-06-15 23:00:00", tz="UTC"),
            "game_pk": 745642,
            "at_bat_number": 1,
            "pitch_number": 1,
            "inning": 1,
            "inning_topbot": "Top",
            "pitcher": 100,
            "batter": 200,
            "pitch_type": "FF",
            "release_speed": 94.5,
            "release_spin_rate": 2300.0,
            "plate_x": 0.0,
            "plate_z": 2.5,
            "zone": 5,
            "balls": 0,
            "strikes": 0,
            "outs_when_up": 0,
            "on_1b": None,
            "on_2b": None,
            "on_3b": None,
            "description": "ball",
            "events": None,
            "home_score": 0,
            "away_score": 0,
        }
    )


def test_happy_path_mapping() -> None:
    ingest = datetime(2024, 6, 15, 23, 0, 1, tzinfo=UTC)
    evt = row_to_pitch_event(_base_row(), ingest_time=ingest)
    assert evt.game_pk == 745642
    assert evt.pitcher_id == 100
    assert evt.batter_id == 200
    assert evt.pitch_type == "FF"
    assert evt.release_speed == pytest.approx(94.5)
    assert evt.ingest_time == ingest


def test_nan_numerics_coerce_to_none() -> None:
    row = _base_row()
    row["release_speed"] = math.nan
    row["release_spin_rate"] = math.nan
    evt = row_to_pitch_event(row, ingest_time=datetime.now(UTC))
    assert evt.release_speed is None
    assert evt.release_spin_rate is None


def test_empty_string_description_is_none() -> None:
    row = _base_row()
    row["description"] = ""
    row["events"] = "   "
    evt = row_to_pitch_event(row, ingest_time=datetime.now(UTC))
    assert evt.description is None
    assert evt.events is None


def test_top_bot_normalization() -> None:
    row = _base_row()
    row["inning_topbot"] = "bottom"
    evt = row_to_pitch_event(row, ingest_time=datetime.now(UTC))
    assert evt.inning_topbot == "Bot"
