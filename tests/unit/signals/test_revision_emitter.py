"""Unit tests for the revision emitter.

Covers each ADR 0017 category that the emitter can produce
(material_update, baseline_confirmed) plus the no-op cases.
suppressed_by_governance is not exercised here because the emitter
does not produce it — that category is the reconciliation layer's
output exclusively.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

import pytest

from ingestion.replay_engine.events import MatchupRevisionEvent
from signals.matchup_signal import MatchupSignal
from signals.revision_emitter import detect_revision


def _make_signal(
    *,
    signal_value: float = 0.05,
    confidence_band: Literal["full", "reduced", "suppressed"] = "full",
    lineup_state_at_emission: Literal["confirmed", "uncertain", "projected"] = "confirmed",
    game_pk: int = 745123,
    at_bat_number: int = 12,
    pitch_number: int = 3,
    pitcher_id: int = 605400,
    batter_id: int = 660271,
) -> MatchupSignal:
    return MatchupSignal(
        event_time=datetime(2024, 7, 4, 19, 30, 0, tzinfo=UTC),
        game_pk=game_pk,
        at_bat_number=at_bat_number,
        pitch_number=pitch_number,
        pitcher_id=pitcher_id,
        batter_id=batter_id,
        handedness_matchup="R_vs_R",
        signal_value=signal_value,
        confidence_band=confidence_band,
        lineup_state_at_emission=lineup_state_at_emission,
    )


# Fixed timestamp for deterministic tests.
_FIXED_TIME = datetime(2024, 7, 4, 20, 0, 0, tzinfo=UTC)


class TestNoOpTransitions:
    """No revision when nothing changed."""

    def test_identical_signals_return_none(self) -> None:
        previous = _make_signal(signal_value=0.05, confidence_band="full")
        new = _make_signal(signal_value=0.05, confidence_band="full")
        assert detect_revision(previous, new, "src-1") is None

    def test_confidence_dropping_returns_none(self) -> None:
        """Confidence going down with no value change does not warrant a revision.

        This case should not occur in practice — confidence only rises as
        lineups confirm. But if it ever does, we treat it as a no-op
        rather than silently emit a baseline_confirmed with backwards
        semantics.
        """
        previous = _make_signal(signal_value=0.05, confidence_band="full")
        new = _make_signal(signal_value=0.05, confidence_band="reduced")
        assert detect_revision(previous, new, "src-1") is None

    def test_confidence_flat_with_value_unchanged_returns_none(self) -> None:
        previous = _make_signal(signal_value=-0.10, confidence_band="reduced")
        new = _make_signal(signal_value=-0.10, confidence_band="reduced")
        assert detect_revision(previous, new, "src-1") is None


class TestMaterialUpdate:
    """signal_value changed between previous and new."""

    def test_value_change_with_confidence_unchanged(self) -> None:
        previous = _make_signal(signal_value=-0.10, confidence_band="reduced")
        new = _make_signal(signal_value=0.05, confidence_band="reduced")
        revision = detect_revision(previous, new, "src-1", revision_event_time=_FIXED_TIME)
        assert revision is not None
        assert revision.revision_type == "material_update"
        assert revision.previous_signal_value == -0.10
        assert revision.current_signal_value == 0.05

    def test_value_change_with_confidence_rise(self) -> None:
        """The canonical lineup-confirmation case: value changes AND confidence rises."""
        previous = _make_signal(signal_value=-0.10, confidence_band="reduced")
        new = _make_signal(signal_value=0.05, confidence_band="full")
        revision = detect_revision(previous, new, "src-1", revision_event_time=_FIXED_TIME)
        assert revision is not None
        assert revision.revision_type == "material_update"
        assert revision.previous_confidence_band == "reduced"
        assert revision.current_confidence_band == "full"

    def test_value_change_from_suppressed_to_active(self) -> None:
        """Edge case: a projected signal becomes confirmed with a different value."""
        previous = _make_signal(signal_value=0.0, confidence_band="suppressed")
        new = _make_signal(signal_value=0.05, confidence_band="full")
        revision = detect_revision(previous, new, "src-1", revision_event_time=_FIXED_TIME)
        assert revision is not None
        assert revision.revision_type == "material_update"


class TestBaselineConfirmed:
    """signal_value identical but confidence rose."""

    def test_reduced_to_full_with_same_value(self) -> None:
        """Canonical: projected batter happened to match actual; only confidence rose."""
        previous = _make_signal(signal_value=0.05, confidence_band="reduced")
        new = _make_signal(signal_value=0.05, confidence_band="full")
        revision = detect_revision(previous, new, "src-1", revision_event_time=_FIXED_TIME)
        assert revision is not None
        assert revision.revision_type == "baseline_confirmed"
        assert revision.previous_signal_value == revision.current_signal_value

    def test_suppressed_to_reduced_with_same_value(self) -> None:
        previous = _make_signal(signal_value=0.05, confidence_band="suppressed")
        new = _make_signal(signal_value=0.05, confidence_band="reduced")
        revision = detect_revision(previous, new, "src-1", revision_event_time=_FIXED_TIME)
        assert revision is not None
        assert revision.revision_type == "baseline_confirmed"

    def test_suppressed_to_full_with_same_value(self) -> None:
        previous = _make_signal(signal_value=0.05, confidence_band="suppressed")
        new = _make_signal(signal_value=0.05, confidence_band="full")
        revision = detect_revision(previous, new, "src-1", revision_event_time=_FIXED_TIME)
        assert revision is not None
        assert revision.revision_type == "baseline_confirmed"


class TestEventPayload:
    """Verify the emitted revision carries everything ADR 0017 promises."""

    def test_natural_key_propagates_from_new_signal(self) -> None:
        previous = _make_signal(game_pk=111, at_bat_number=22, pitch_number=3)
        new = _make_signal(game_pk=111, at_bat_number=22, pitch_number=3, signal_value=999.0)
        revision = detect_revision(previous, new, "src-1", revision_event_time=_FIXED_TIME)
        assert revision is not None
        assert (revision.game_pk, revision.at_bat_number, revision.pitch_number) == (111, 22, 3)

    def test_pitcher_and_batter_propagate_from_new_signal(self) -> None:
        """batter_id should come from the new signal — that is the actual batter post-revision."""
        previous = _make_signal(batter_id=111, signal_value=-0.10)
        new = _make_signal(batter_id=222, signal_value=0.05)
        revision = detect_revision(previous, new, "src-1", revision_event_time=_FIXED_TIME)
        assert revision is not None
        assert revision.batter_id == 222

    def test_source_event_id_propagates(self) -> None:
        previous = _make_signal(signal_value=-0.10)
        new = _make_signal(signal_value=0.05)
        revision = detect_revision(
            previous,
            new,
            "lineup_confirmation:745123:2024-07-04T18:55Z",
            revision_event_time=_FIXED_TIME,
        )
        assert revision is not None
        assert revision.source_event_id == "lineup_confirmation:745123:2024-07-04T18:55Z"

    def test_revision_event_time_defaults_to_now_when_not_provided(self) -> None:
        previous = _make_signal(signal_value=-0.10)
        new = _make_signal(signal_value=0.05)
        before = datetime.now(UTC)
        revision = detect_revision(previous, new, "src-1")
        after = datetime.now(UTC)
        assert revision is not None
        assert before <= revision.event_time <= after

    def test_event_time_uses_provided_timestamp_when_passed(self) -> None:
        previous = _make_signal(signal_value=-0.10)
        new = _make_signal(signal_value=0.05)
        revision = detect_revision(previous, new, "src-1", revision_event_time=_FIXED_TIME)
        assert revision is not None
        assert revision.event_time == _FIXED_TIME

    def test_returns_matchup_revision_event_instance(self) -> None:
        previous = _make_signal(signal_value=-0.10)
        new = _make_signal(signal_value=0.05)
        revision = detect_revision(previous, new, "src-1", revision_event_time=_FIXED_TIME)
        assert isinstance(revision, MatchupRevisionEvent)


class TestNaturalKeyMismatch:
    """Caller must group signals by natural key before calling."""

    def test_different_game_pk_raises(self) -> None:
        previous = _make_signal(game_pk=111)
        new = _make_signal(game_pk=222)
        with pytest.raises(ValueError, match="mismatched natural keys"):
            detect_revision(previous, new, "src-1")

    def test_different_at_bat_number_raises(self) -> None:
        previous = _make_signal(at_bat_number=11)
        new = _make_signal(at_bat_number=12)
        with pytest.raises(ValueError, match="mismatched natural keys"):
            detect_revision(previous, new, "src-1")

    def test_different_pitch_number_raises(self) -> None:
        previous = _make_signal(pitch_number=1)
        new = _make_signal(pitch_number=2)
        with pytest.raises(ValueError, match="mismatched natural keys"):
            detect_revision(previous, new, "src-1")
