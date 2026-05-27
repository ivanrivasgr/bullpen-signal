"""Unit tests for the ADR 0015 projected-batter hierarchy.

Tests cover each layer of the hierarchy in isolation by constructing
LineupCache instances with controlled fixture data. No real cache file
is read.
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from datetime import date
from pathlib import Path

import pytest

from ingestion.replay_engine.lineup_projection import (
    GameLineup,
    LineupCache,
    compute_projected_batter,
)


def _write_cache(tmp_path: Path, records: list[dict]) -> Path:
    cache_path = tmp_path / "lineups.json"
    payload = {"lineups": records}
    with cache_path.open("w") as f:
        json.dump(payload, f)
    return cache_path


class TestPrimaryLookup:
    """Layer 1: previous game lineup."""

    def test_returns_batter_from_previous_day_game(self, tmp_path: Path) -> None:
        records = [
            {
                "game_pk": 745122,
                "game_date": "2024-04-14",
                "team_id": 119,
                "side": "home",
                "batting_order": [101, 102, 103, 104, 105, 106, 107, 108, 109],
            }
        ]
        cache = LineupCache(_write_cache(tmp_path, records))
        result = compute_projected_batter(
            team_id=119,
            lineup_position=3,
            projection_date=date(2024, 4, 15),
            cache=cache,
        )
        assert result == 103


class TestWalkbackFallback:
    """Layer 2: walk back day by day until a played game is found."""

    def test_walks_back_through_off_day(self, tmp_path: Path) -> None:
        # Team played on April 12, not April 13 or 14. Projecting for April 15.
        records = [
            {
                "game_pk": 745120,
                "game_date": "2024-04-12",
                "team_id": 119,
                "side": "home",
                "batting_order": [201, 202, 203, 204, 205, 206, 207, 208, 209],
            }
        ]
        cache = LineupCache(_write_cache(tmp_path, records))
        result = compute_projected_batter(
            team_id=119,
            lineup_position=1,
            projection_date=date(2024, 4, 15),
            cache=cache,
        )
        assert result == 201

    def test_prefers_most_recent_game_when_multiple_exist(self, tmp_path: Path) -> None:
        records = [
            {
                "game_pk": 745118,
                "game_date": "2024-04-10",
                "team_id": 119,
                "side": "home",
                "batting_order": [301, 302, 303, 304, 305, 306, 307, 308, 309],
            },
            {
                "game_pk": 745125,
                "game_date": "2024-04-14",
                "team_id": 119,
                "side": "home",
                "batting_order": [401, 402, 403, 404, 405, 406, 407, 408, 409],
            },
        ]
        cache = LineupCache(_write_cache(tmp_path, records))
        result = compute_projected_batter(
            team_id=119,
            lineup_position=5,
            projection_date=date(2024, 4, 15),
            cache=cache,
        )
        assert result == 405


class TestOpeningDayFallback:
    """Layer 3: opening day fallback when no prior game in the cache."""

    def test_uses_opening_day_when_no_prior_game(self, tmp_path: Path) -> None:
        # Cache only has opening day (April 1). Projecting for April 2,
        # the day after opening day, with no walk-back match.
        records = [
            {
                "game_pk": 745100,
                "game_date": "2024-04-01",
                "team_id": 119,
                "side": "home",
                "batting_order": [501, 502, 503, 504, 505, 506, 507, 508, 509],
            }
        ]
        cache = LineupCache(_write_cache(tmp_path, records))
        # Project for April 2 — walk-back finds April 1 directly (within MAX_WALKBACK_DAYS).
        # To force opening-day path, project for a date 20 days after with no intervening games.
        result = compute_projected_batter(
            team_id=119,
            lineup_position=4,
            projection_date=date(2024, 4, 22),
            cache=cache,
        )
        assert result == 504

    def test_returns_none_for_projection_at_or_before_opening_day(self, tmp_path: Path) -> None:
        records = [
            {
                "game_pk": 745100,
                "game_date": "2024-04-01",
                "team_id": 119,
                "side": "home",
                "batting_order": [601, 602, 603, 604, 605, 606, 607, 608, 609],
            }
        ]
        cache = LineupCache(_write_cache(tmp_path, records))
        result = compute_projected_batter(
            team_id=119,
            lineup_position=1,
            projection_date=date(2024, 4, 1),
            cache=cache,
        )
        assert result is None


class TestCacheMisses:
    """Cache-miss behavior across all layers."""

    def test_returns_none_when_team_has_no_lineups_at_all(self, tmp_path: Path) -> None:
        records = [
            {
                "game_pk": 745122,
                "game_date": "2024-04-14",
                "team_id": 119,
                "side": "home",
                "batting_order": [101, 102, 103, 104, 105, 106, 107, 108, 109],
            }
        ]
        cache = LineupCache(_write_cache(tmp_path, records))
        result = compute_projected_batter(
            team_id=999,
            lineup_position=1,
            projection_date=date(2024, 4, 15),
            cache=cache,
        )
        assert result is None

    def test_returns_none_for_lineup_position_out_of_range(self, tmp_path: Path) -> None:
        records = [
            {
                "game_pk": 745122,
                "game_date": "2024-04-14",
                "team_id": 119,
                "side": "home",
                "batting_order": [101, 102, 103, 104, 105, 106, 107, 108, 109],
            }
        ]
        cache = LineupCache(_write_cache(tmp_path, records))
        result = compute_projected_batter(
            team_id=119,
            lineup_position=10,
            projection_date=date(2024, 4, 15),
            cache=cache,
        )
        assert result is None

    def test_skips_empty_batting_orders_when_walking_back(self, tmp_path: Path) -> None:
        # April 14 has an empty batting order (game found but lineup not posted).
        # April 12 has a real lineup. Walk-back should skip April 14 and find April 12.
        records = [
            {
                "game_pk": 745120,
                "game_date": "2024-04-12",
                "team_id": 119,
                "side": "home",
                "batting_order": [701, 702, 703, 704, 705, 706, 707, 708, 709],
            },
            {
                "game_pk": 745122,
                "game_date": "2024-04-14",
                "team_id": 119,
                "side": "home",
                "batting_order": [],
            },
        ]
        cache = LineupCache(_write_cache(tmp_path, records))
        result = compute_projected_batter(
            team_id=119,
            lineup_position=2,
            projection_date=date(2024, 4, 15),
            cache=cache,
        )
        assert result == 702


class TestCacheLoading:
    """LineupCache file IO behavior."""

    def test_raises_friendly_error_when_cache_missing(self, tmp_path: Path) -> None:
        cache = LineupCache(tmp_path / "nonexistent.json")
        with pytest.raises(FileNotFoundError, match="precompute_lineups"):
            cache.load()

    def test_load_is_idempotent(self, tmp_path: Path) -> None:
        records = [
            {
                "game_pk": 745122,
                "game_date": "2024-04-14",
                "team_id": 119,
                "side": "home",
                "batting_order": [101, 102, 103, 104, 105, 106, 107, 108, 109],
            }
        ]
        cache = LineupCache(_write_cache(tmp_path, records))
        cache.load()
        cache.load()
        assert cache.get_for_team_on_date(119, date(2024, 4, 14)) is not None


class TestGameLineupDataclass:
    """Sanity tests for the GameLineup dataclass."""

    def test_gamelineup_is_immutable(self) -> None:
        lineup = GameLineup(
            game_pk=745122,
            game_date=date(2024, 4, 14),
            team_id=119,
            side="home",
            batting_order=[101, 102, 103],
        )
        with pytest.raises(FrozenInstanceError):
            lineup.team_id = 999  # type: ignore[misc]
