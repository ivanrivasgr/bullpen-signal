"""Unit tests for the matchup signal generator.

Tests cover three concerns:

1. The lineup_state -> confidence_band mapping defined in ADR 0016.
2. The placeholder signal_value lookup per handedness_matchup.
3. Edge cases: unknown handedness, unknown lineup_state, missing fields.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from signals.matchup_signal import MatchupSignal, generate_matchup_signal


def _base_event(**overrides) -> dict:
    """A complete silver_matchup_events row with overridable fields."""
    base = {
        "event_time": datetime(2024, 7, 4, 19, 30, 0, tzinfo=UTC),
        "game_pk": 745123,
        "at_bat_number": 12,
        "pitch_number": 3,
        "pitcher_id": 605400,
        "batter_id": 660271,
        "lineup_state": "confirmed",
        "handedness_matchup": "R_vs_R",
    }
    base.update(overrides)
    return base


class TestLineupStateToConfidenceBand:
    """ADR 0016 contract: lineup_state maps to confidence_band 1:1."""

    def test_confirmed_maps_to_full(self) -> None:
        signal = generate_matchup_signal(_base_event(lineup_state="confirmed"))
        assert signal.confidence_band == "full"
        assert signal.lineup_state_at_emission == "confirmed"

    def test_uncertain_maps_to_reduced(self) -> None:
        signal = generate_matchup_signal(_base_event(lineup_state="uncertain"))
        assert signal.confidence_band == "reduced"
        assert signal.lineup_state_at_emission == "uncertain"

    def test_projected_maps_to_suppressed(self) -> None:
        signal = generate_matchup_signal(_base_event(lineup_state="projected"))
        assert signal.confidence_band == "suppressed"
        assert signal.lineup_state_at_emission == "projected"

    def test_unknown_lineup_state_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="unknown lineup_state"):
            generate_matchup_signal(_base_event(lineup_state="bogus"))


class TestPlaceholderSignalValues:
    """The signal_value table is arbitrary but consistent across calls."""

    def test_r_vs_r_gives_slight_pitcher_advantage(self) -> None:
        signal = generate_matchup_signal(_base_event(handedness_matchup="R_vs_R"))
        assert signal.signal_value == 0.05

    def test_r_vs_l_gives_batter_advantage(self) -> None:
        signal = generate_matchup_signal(_base_event(handedness_matchup="R_vs_L"))
        assert signal.signal_value == -0.10

    def test_l_vs_r_gives_batter_advantage(self) -> None:
        signal = generate_matchup_signal(_base_event(handedness_matchup="L_vs_R"))
        assert signal.signal_value == -0.10

    def test_l_vs_l_gives_slight_pitcher_advantage(self) -> None:
        signal = generate_matchup_signal(_base_event(handedness_matchup="L_vs_L"))
        assert signal.signal_value == 0.08


class TestUnknownHandednessMatchup:
    """When the matchup is unknown, signal_value falls back to neutral (0.0)."""

    def test_none_handedness_gives_zero_signal(self) -> None:
        signal = generate_matchup_signal(_base_event(handedness_matchup=None))
        assert signal.signal_value == 0.0
        assert signal.handedness_matchup is None

    def test_unknown_handedness_string_also_gives_zero_signal(self) -> None:
        """Any unrecognized matchup string falls through to the default lookup."""
        signal = generate_matchup_signal(_base_event(handedness_matchup="X_vs_Y"))
        assert signal.signal_value == 0.0


class TestSuppressedSignalsAreStillEmitted:
    """Phase 3 needs suppressed signals to evaluate counterfactuals."""

    def test_projected_state_still_carries_signal_value(self) -> None:
        """A suppressed signal is not a zeroed signal — it still carries the placeholder value
        so Phase 3 can evaluate the counterfactual."""
        signal = generate_matchup_signal(
            _base_event(lineup_state="projected", handedness_matchup="R_vs_L")
        )
        assert signal.confidence_band == "suppressed"
        assert signal.signal_value == -0.10
        assert signal.handedness_matchup == "R_vs_L"

    def test_uncertain_state_carries_signal_value(self) -> None:
        signal = generate_matchup_signal(
            _base_event(lineup_state="uncertain", handedness_matchup="L_vs_L")
        )
        assert signal.confidence_band == "reduced"
        assert signal.signal_value == 0.08


class TestRequiredFields:
    """A missing required field should fail loudly, not silently produce garbage."""

    def test_missing_lineup_state_raises_key_error(self) -> None:
        event = _base_event()
        del event["lineup_state"]
        with pytest.raises(KeyError):
            generate_matchup_signal(event)

    def test_missing_game_pk_raises_key_error(self) -> None:
        event = _base_event()
        del event["game_pk"]
        with pytest.raises(KeyError):
            generate_matchup_signal(event)


class TestModelOutputShape:
    """The MatchupSignal Pydantic model carries the fields downstream needs."""

    def test_all_input_identifiers_propagate(self) -> None:
        event = _base_event(
            game_pk=999,
            at_bat_number=5,
            pitch_number=2,
            pitcher_id=111,
            batter_id=222,
        )
        signal = generate_matchup_signal(event)
        assert signal.game_pk == 999
        assert signal.at_bat_number == 5
        assert signal.pitch_number == 2
        assert signal.pitcher_id == 111
        assert signal.batter_id == 222

    def test_event_time_propagates(self) -> None:
        event_time = datetime(2024, 8, 15, 20, 5, 0, tzinfo=UTC)
        signal = generate_matchup_signal(_base_event(event_time=event_time))
        assert signal.event_time == event_time

    def test_returns_matchup_signal_instance(self) -> None:
        signal = generate_matchup_signal(_base_event())
        assert isinstance(signal, MatchupSignal)
