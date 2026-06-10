"""Tests for team inference and the abbreviation->team_id reference map."""

from __future__ import annotations

from datetime import UTC, datetime

from ingestion.replay_engine.events import PitchEvent
from ingestion.replay_engine.team_lookup import (
    abbreviation_to_team_id,
    load_abbreviation_to_team_id,
)
from ingestion.replay_engine.uncertainty_window import _infer_batting_team_id


def _pitch(inning_topbot: str, home_team_id: int | None, away_team_id: int | None) -> PitchEvent:
    return PitchEvent(
        event_time=datetime(2024, 4, 15, 19, 0, 0, tzinfo=UTC),
        ingest_time=datetime(2024, 4, 15, 19, 0, 0, tzinfo=UTC),
        game_pk=746974,
        at_bat_number=1,
        pitch_number=1,
        inning=1,
        inning_topbot=inning_topbot,
        pitcher_id=605400,
        batter_id=660271,
        balls=0,
        strikes=0,
        outs_when_up=0,
        home_score=0,
        away_score=0,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
    )


class TestInferBattingTeam:
    """Top of the inning: away team bats. Bottom: home team bats."""

    def test_top_of_inning_away_team_bats(self) -> None:
        pitch = _pitch("Top", home_team_id=111, away_team_id=114)
        assert _infer_batting_team_id(pitch) == 114

    def test_bottom_of_inning_home_team_bats(self) -> None:
        pitch = _pitch("Bot", home_team_id=111, away_team_id=114)
        assert _infer_batting_team_id(pitch) == 111

    def test_missing_team_id_returns_none(self) -> None:
        # An event built without team context degrades gracefully.
        pitch = _pitch("Top", home_team_id=None, away_team_id=None)
        assert _infer_batting_team_id(pitch) is None


class TestAbbreviationMap:
    """The reference map derived from observed game data."""

    def test_map_has_thirty_teams(self) -> None:
        mapping = load_abbreviation_to_team_id()
        assert len(mapping) == 30

    def test_statcast_specific_abbreviations_resolve(self) -> None:
        # The four teams where Statcast differs from StatsAPI fileCode.
        assert abbreviation_to_team_id("LAA") == 108
        assert abbreviation_to_team_id("AZ") == 109
        assert abbreviation_to_team_id("LAD") == 119
        assert abbreviation_to_team_id("WSH") == 120

    def test_unknown_abbreviation_returns_none(self) -> None:
        assert abbreviation_to_team_id("ZZZ") is None
