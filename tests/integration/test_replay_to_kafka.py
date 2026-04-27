"""End-to-end integration test: synthetic Statcast → AvroEventPublisher → Kafka.

Runs a small synthetic replay through the real publisher and asserts that
both pitches.raw and game_state.raw receive the expected Avro messages,
decodable via the Schema Registry.

Run with: `pytest -m integration` or `pytest tests/integration/`.
Skipped by default in normal `pytest` invocations.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from ingestion.replay_engine.avro_publisher import AvroEventPublisher
from ingestion.replay_engine.run import _run_replay
from tests.integration.conftest import consume_until_quiet

pytestmark = [pytest.mark.integration, pytest.mark.slow]


def _synthetic_statcast_df() -> pd.DataFrame:
    """Build a 12-pitch DataFrame that exercises every game-state transition.

    Layout:
      pitch 1: game_pk=999001, inn 1 Top, pitcher A, score 0-0   → game_start
      pitch 2: same                                              → no transition
      pitch 3: same, score 0-1                                   → scoring_play
      pitch 4: pitcher B (mid half-inning)                       → pitching_change
      pitch 5: same                                              → no transition
      pitch 6: inn 1 Bot, pitcher C, score 0-1                   → inning_start
      pitch 7: same                                              → no transition
      pitch 8: inn 1 Bot, pitcher C, score 1-1                   → scoring_play
      pitch 9: pitcher D                                         → pitching_change
      pitch 10: inn 2 Top, pitcher E                             → inning_start
      pitch 11: same                                             → no transition
      pitch 12: same                                             → no transition

    Expected: 12 pitches in pitches.raw, 6 events in game_state.raw
    (1 game_start + 2 inning_start + 2 pitching_change + 3 scoring_play... wait,
    there are 2 scoring_plays (pitch 3 home_score 0->1... actually away_score, and
    pitch 8 home_score 0->1). So: 1 + 2 + 2 + 2 = 7. Recount in the assertion.
    """
    base_time = datetime(2024, 7, 4, 19, 0, 0, tzinfo=UTC)

    rows = [
        # (delta_min, inning, topbot, pitcher, batter, ab, pn, balls, strikes, home, away)
        (0, 1, "Top", 605400, 660271, 1, 1, 0, 0, 0, 0),  # game_start
        (1, 1, "Top", 605400, 660271, 1, 2, 1, 0, 0, 0),  # —
        (2, 1, "Top", 605400, 660271, 1, 3, 1, 1, 0, 1),  # scoring_play (away)
        (3, 1, "Top", 519242, 660272, 2, 1, 0, 0, 0, 1),  # pitching_change
        (4, 1, "Top", 519242, 660272, 2, 2, 0, 1, 0, 1),  # —
        (5, 1, "Bot", 700001, 600001, 3, 1, 0, 0, 0, 1),  # inning_start
        (6, 1, "Bot", 700001, 600001, 3, 2, 1, 0, 0, 1),  # —
        (7, 1, "Bot", 700001, 600001, 3, 3, 1, 1, 1, 1),  # scoring_play (home)
        (8, 1, "Bot", 700002, 600002, 4, 1, 0, 0, 1, 1),  # pitching_change
        (9, 2, "Top", 605400, 660271, 5, 1, 0, 0, 1, 1),  # inning_start
        (10, 2, "Top", 605400, 660271, 5, 2, 1, 0, 1, 1),  # —
        (11, 2, "Top", 605400, 660271, 5, 3, 1, 1, 1, 1),  # —
    ]

    df = pd.DataFrame(
        [
            {
                "event_time": pd.Timestamp(base_time + timedelta(minutes=delta)),
                "game_pk": 999001,
                "at_bat_number": ab,
                "pitch_number": pn,
                "inning": inn,
                "inning_topbot": topbot,
                "pitcher": pitcher,
                "batter": batter,
                "pitch_type": "FF",
                "release_speed": 95.0,
                "release_spin_rate": 2400.0,
                "plate_x": 0.0,
                "plate_z": 2.5,
                "zone": 5,
                "balls": balls,
                "strikes": strikes,
                "outs_when_up": 0,
                "on_1b": None,
                "on_2b": None,
                "on_3b": None,
                "description": "ball",
                "events": None,
                "home_score": home,
                "away_score": away,
            }
            for (delta, inn, topbot, pitcher, batter, ab, pn, balls, strikes, home, away) in rows
        ]
    )
    return df


@pytest.fixture
def synthetic_replay_setup(clean_topic, monkeypatch):
    """Wipe target topics and disable replay noise for deterministic counts.

    The replay engine's noise injector emits duplicates, late arrivals, and
    corrections at configurable probabilities. Those behaviors are tested
    elsewhere (unit tests on noise_injector). For this end-to-end wiring
    test we want exact counts, so we set every noise prob to 0.
    """
    from ingestion.replay_engine.config import config as replay_config

    monkeypatch.setattr(replay_config, "replay_noise_late_arrival_prob", 0.0)
    monkeypatch.setattr(replay_config, "replay_noise_duplicate_prob", 0.0)
    monkeypatch.setattr(replay_config, "replay_noise_correction_prob", 0.0)

    clean_topic("pitches.raw")
    clean_topic("game_state.raw")
    clean_topic("corrections.cdc")
    yield


def test_replay_publishes_pitches_to_pitches_raw(
    synthetic_replay_setup, avro_consumer_factory
) -> None:
    """A 12-pitch synthetic replay produces 12 Avro-decodable messages on pitches.raw."""
    publisher = AvroEventPublisher(bootstrap_servers="localhost:19092")
    df = _synthetic_statcast_df()

    _run_replay(df, publisher, speed=1000.0, rng=random.Random(42))
    publisher.flush(timeout=10.0)

    consumer, deserializer = avro_consumer_factory("pitches.raw", "pitches")
    payloads = consume_until_quiet(consumer, deserializer)

    # All 12 pitches landed.
    assert len(payloads) == 12, (
        f"Expected 12 pitches, got {len(payloads)}. "
        f"Payloads: {[(p.get('at_bat_number'), p.get('pitch_number')) for p in payloads]}"
    )

    # Schema validity: every payload should have the full PitchEvent field set.
    required_fields = {
        "event_time",
        "ingest_time",
        "game_pk",
        "at_bat_number",
        "pitch_number",
        "inning",
        "inning_topbot",
        "pitcher_id",
        "batter_id",
        "balls",
        "strikes",
        "outs_when_up",
        "home_score",
        "away_score",
    }
    for p in payloads:
        missing = required_fields - set(p.keys())
        assert not missing, f"PitchEvent missing fields {missing}: {p}"

    # All belong to the synthetic game.
    assert {p["game_pk"] for p in payloads} == {999001}


def test_replay_publishes_game_state_transitions(
    synthetic_replay_setup, avro_consumer_factory
) -> None:
    """The 12-pitch synthetic replay derives the expected game-state transitions."""
    publisher = AvroEventPublisher(bootstrap_servers="localhost:19092")
    df = _synthetic_statcast_df()

    _run_replay(df, publisher, speed=1000.0, rng=random.Random(42))
    publisher.flush(timeout=10.0)

    consumer, deserializer = avro_consumer_factory("game_state.raw", "gamestate")
    payloads = consume_until_quiet(consumer, deserializer)

    event_types = [p["event_type"] for p in payloads]

    # Expected derived events (see _synthetic_statcast_df docstring):
    #   1 game_start
    #   2 inning_start (pitch 6 Bot, pitch 10 Top inn 2)
    #   2 pitching_change (pitch 4, pitch 9)
    #   2 scoring_play (pitch 3 away, pitch 8 home)
    expected_counts = {
        "game_start": 1,
        "inning_start": 2,
        "pitching_change": 2,
        "scoring_play": 2,
    }
    actual_counts = {et: event_types.count(et) for et in expected_counts}
    assert actual_counts == expected_counts, (
        f"Game state event counts mismatch.\n"
        f"  expected: {expected_counts}\n"
        f"  actual:   {actual_counts}\n"
        f"  full sequence: {event_types}"
    )

    # Total: 7 derived events.
    assert len(payloads) == 7, f"Expected 7 game state events, got {len(payloads)}: {event_types}"

    # All belong to the synthetic game.
    assert {p["game_pk"] for p in payloads} == {999001}
