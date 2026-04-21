"""Unit tests for the noise injector.

These tests are fully synthetic; they do not touch Kafka or Statcast.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from ingestion.noise_injector import maybe_inject_noise
from ingestion.replay_engine.events import CorrectionEvent, PitchEvent


def _pitch(pitch_type: str = "FF") -> PitchEvent:
    now = datetime(2024, 6, 15, 23, 0, 0, tzinfo=UTC)
    return PitchEvent(
        event_time=now,
        ingest_time=now,
        game_pk=745642,
        at_bat_number=1,
        pitch_number=1,
        inning=1,
        inning_topbot="Top",
        pitcher_id=100,
        batter_id=200,
        pitch_type=pitch_type,
        release_speed=94.5,
        release_spin_rate=2300.0,
        plate_x=0.0,
        plate_z=2.5,
        zone=5,
        balls=0,
        strikes=0,
        outs_when_up=0,
        home_score=0,
        away_score=0,
    )


def test_original_event_always_yielded_first() -> None:
    produced = list(
        maybe_inject_noise(
            _pitch(),
            late_arrival_prob=0.0,
            duplicate_prob=0.0,
            correction_prob=0.0,
            rng=random.Random(1),
        )
    )
    assert len(produced) == 1
    assert isinstance(produced[0], PitchEvent)
    assert not produced[0].is_duplicate
    assert not produced[0].is_late_arrival


def test_duplicate_emitted_when_probability_is_one() -> None:
    produced = list(
        maybe_inject_noise(
            _pitch(),
            late_arrival_prob=0.0,
            duplicate_prob=1.0,
            correction_prob=0.0,
            rng=random.Random(1),
        )
    )
    assert len(produced) == 2
    assert produced[1].is_duplicate


def test_late_arrival_has_earlier_event_time() -> None:
    pitch = _pitch()
    produced = list(
        maybe_inject_noise(
            pitch,
            late_arrival_prob=1.0,
            duplicate_prob=0.0,
            correction_prob=0.0,
            rng=random.Random(1),
        )
    )
    late = produced[-1]
    assert isinstance(late, PitchEvent)
    assert late.is_late_arrival
    assert late.event_time < pitch.event_time


def test_correction_event_targets_original_pitch() -> None:
    pitch = _pitch(pitch_type="FF")
    produced = list(
        maybe_inject_noise(
            pitch,
            late_arrival_prob=0.0,
            duplicate_prob=0.0,
            correction_prob=1.0,
            rng=random.Random(1),
        )
    )
    corrections = [e for e in produced if isinstance(e, CorrectionEvent)]
    assert len(corrections) == 1
    correction = corrections[0]
    assert correction.field == "pitch_type"
    assert correction.old_value == "FF"
    assert correction.new_value != "FF"
    assert correction.original_pitch_uid == "745642:1:1"


@pytest.mark.parametrize("seed", [1, 7, 42, 101])
def test_determinism_across_seeds(seed: int) -> None:
    """Same seed, same pitch, same output. Non-negotiable for replay reproducibility."""
    pitch = _pitch()
    out_a = list(
        maybe_inject_noise(
            pitch,
            late_arrival_prob=0.3,
            duplicate_prob=0.3,
            correction_prob=0.3,
            rng=random.Random(seed),
        )
    )
    out_b = list(
        maybe_inject_noise(
            pitch,
            late_arrival_prob=0.3,
            duplicate_prob=0.3,
            correction_prob=0.3,
            rng=random.Random(seed),
        )
    )
    assert [type(e).__name__ for e in out_a] == [type(e).__name__ for e in out_b]
    assert len(out_a) == len(out_b)
