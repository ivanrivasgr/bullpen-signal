"""Unit tests for game_state_deriver.derive_game_state_events.

Each test exercises one transition rule in isolation. The deriver is a pure
function so tests are quick and don't need fixtures beyond a builder helper.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ingestion.replay_engine.events import PitchEvent
from ingestion.replay_engine.game_state_deriver import derive_game_state_events


def _pitch(
    *,
    event_time: datetime | None = None,
    game_pk: int = 745123,
    inning: int = 1,
    inning_topbot: str = "Top",
    pitcher_id: int = 605400,
    batter_id: int = 660271,
    home_score: int = 0,
    away_score: int = 0,
    at_bat_number: int = 1,
    pitch_number: int = 1,
) -> PitchEvent:
    """Minimal PitchEvent for transition testing."""
    return PitchEvent(
        event_time=event_time or datetime(2024, 7, 4, 19, 0, 0, tzinfo=UTC),
        ingest_time=datetime(2024, 7, 4, 19, 0, 0, tzinfo=UTC),
        game_pk=game_pk,
        at_bat_number=at_bat_number,
        pitch_number=pitch_number,
        inning=inning,
        inning_topbot=inning_topbot,  # type: ignore[arg-type]
        pitcher_id=pitcher_id,
        batter_id=batter_id,
        balls=0,
        strikes=0,
        outs_when_up=0,
        home_score=home_score,
        away_score=away_score,
    )


class TestGameStart:
    def test_first_pitch_emits_game_start(self) -> None:
        first = _pitch()
        events = derive_game_state_events(previous_pitch=None, current_pitch=first)
        assert len(events) == 1
        assert events[0].event_type == "game_start"
        assert events[0].game_pk == first.game_pk
        assert events[0].inning == 1
        assert events[0].next_batter_id == first.batter_id

    def test_game_start_in_top_inning_sets_home_pitcher(self) -> None:
        first = _pitch(inning_topbot="Top", pitcher_id=605400)
        events = derive_game_state_events(previous_pitch=None, current_pitch=first)
        assert events[0].home_pitcher_id == 605400
        assert events[0].away_pitcher_id is None

    def test_game_start_in_bottom_inning_sets_away_pitcher(self) -> None:
        first = _pitch(inning_topbot="Bot", pitcher_id=605400)
        events = derive_game_state_events(previous_pitch=None, current_pitch=first)
        assert events[0].home_pitcher_id is None
        assert events[0].away_pitcher_id == 605400


class TestSamePitchNoTransition:
    def test_consecutive_same_state_emits_nothing(self) -> None:
        prev = _pitch(pitch_number=1)
        curr = _pitch(pitch_number=2)
        events = derive_game_state_events(prev, curr)
        assert events == []


class TestInningTransition:
    def test_inning_change_emits_inning_start(self) -> None:
        prev = _pitch(inning=1, inning_topbot="Top")
        curr = _pitch(inning=1, inning_topbot="Bot")
        events = derive_game_state_events(prev, curr)
        assert len(events) == 1
        assert events[0].event_type == "inning_start"
        assert events[0].inning_topbot == "Bot"

    def test_inning_number_change_emits_inning_start(self) -> None:
        prev = _pitch(inning=1, inning_topbot="Bot")
        curr = _pitch(inning=2, inning_topbot="Top")
        events = derive_game_state_events(prev, curr)
        assert len(events) == 1
        assert events[0].event_type == "inning_start"
        assert events[0].inning == 2


class TestPitchingChange:
    def test_pitcher_change_within_half_inning_emits_pitching_change(self) -> None:
        prev = _pitch(pitcher_id=605400)
        curr = _pitch(pitcher_id=519242)
        events = derive_game_state_events(prev, curr)
        assert len(events) == 1
        assert events[0].event_type == "pitching_change"
        assert events[0].home_pitcher_id == 519242  # Top inning → home pitching

    def test_pitcher_change_at_inning_boundary_does_not_emit_pitching_change(
        self,
    ) -> None:
        """A pitcher change combined with an inning boundary is just inning_start.

        At inning boundaries the new pitcher is expected (different team
        batting), so emitting both inning_start and pitching_change would
        be redundant noise. The contract is: inning_start absorbs the
        implicit pitching change.
        """
        prev = _pitch(inning=1, inning_topbot="Top", pitcher_id=605400)
        curr = _pitch(inning=1, inning_topbot="Bot", pitcher_id=519242)
        events = derive_game_state_events(prev, curr)
        assert len(events) == 1
        assert events[0].event_type == "inning_start"


class TestScoringPlay:
    def test_home_score_increment_emits_scoring_play(self) -> None:
        prev = _pitch(home_score=0)
        curr = _pitch(home_score=1)
        events = derive_game_state_events(prev, curr)
        assert any(e.event_type == "scoring_play" for e in events)

    def test_away_score_increment_emits_scoring_play(self) -> None:
        prev = _pitch(away_score=2)
        curr = _pitch(away_score=3)
        events = derive_game_state_events(prev, curr)
        assert any(e.event_type == "scoring_play" for e in events)

    def test_no_score_change_emits_no_scoring_play(self) -> None:
        prev = _pitch(home_score=1, away_score=1)
        curr = _pitch(home_score=1, away_score=1)
        events = derive_game_state_events(prev, curr)
        assert all(e.event_type != "scoring_play" for e in events)


class TestCombinedTransitions:
    def test_inning_change_with_score_increment_emits_both(self) -> None:
        """A walk-off scoring play in the bottom of the 9th would look like this:
        the score increments AND the half-inning transitions in the next pitch
        of the next half-inning. Both events should be emitted.
        """
        prev = _pitch(inning=9, inning_topbot="Top", home_score=2, away_score=3)
        curr = _pitch(inning=9, inning_topbot="Bot", home_score=2, away_score=4)
        events = derive_game_state_events(prev, curr)
        types = [e.event_type for e in events]
        assert "inning_start" in types
        assert "scoring_play" in types


class TestMixedGamePkRejected:
    def test_different_game_pk_raises(self) -> None:
        prev = _pitch(game_pk=111)
        curr = _pitch(game_pk=222)
        with pytest.raises(ValueError, match="mixed game_pks"):
            derive_game_state_events(prev, curr)
