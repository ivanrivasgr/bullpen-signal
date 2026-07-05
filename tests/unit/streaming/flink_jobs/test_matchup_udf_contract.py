"""Contract test: the streaming UDF path must equal the batch signal path.

ADR 0021's anti-drift guarantee. The streaming matchup job computes the
signal via compute_matchup_fields (wrapped as a Flink UDF); the batch
path computes it via generate_matchup_signal directly. Both must agree
for every handedness matchup and lineup_state, or the reconciliation
measures drift between two implementations instead of the latency cost
the dual-path exists to measure.

This test does not require a Flink cluster — it exercises
compute_matchup_fields, the plain function the UDF wraps, against the
shared pure definition. If the two ever disagree, this fails.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from signals.matchup_calibration import CALIBRATED_SIGNAL_VALUES
from signals.matchup_signal import generate_matchup_signal
from streaming.flink_jobs.matchup.matchup_udf import compute_matchup_fields

_EVENT_TIME = datetime(2024, 4, 15, 19, 0, 0, tzinfo=UTC)
_LINEUP_STATES = ["confirmed", "uncertain", "projected"]


def _all_handedness_matchups() -> list[str | None]:
    # Every key the calibrated map knows, including None (unknown).
    return list(CALIBRATED_SIGNAL_VALUES.keys())


class TestStreamingBatchEquivalence:
    """For every matchup and lineup_state, UDF path == batch path."""

    @pytest.mark.parametrize("handedness_matchup", _all_handedness_matchups())
    @pytest.mark.parametrize("lineup_state", _LINEUP_STATES)
    def test_udf_path_equals_batch_path(
        self, handedness_matchup: str | None, lineup_state: str
    ) -> None:
        # Batch path: the shared pure definition.
        batch = generate_matchup_signal(
            {
                "handedness_matchup": handedness_matchup,
                "lineup_state": lineup_state,
                "event_time": _EVENT_TIME,
                "game_pk": 745123,
                "at_bat_number": 12,
                "pitch_number": 3,
                "pitcher_id": 605400,
                "batter_id": 660271,
            }
        )
        # Streaming path: the plain function the UDF wraps.
        stream_value, stream_band, stream_state = compute_matchup_fields(
            handedness_matchup=handedness_matchup,
            lineup_state=lineup_state,
        )

        assert stream_value == batch.signal_value
        assert stream_band == batch.confidence_band
        assert stream_state == batch.lineup_state_at_emission


class TestUdfPathErrors:
    """The UDF path must raise the same errors as the batch path."""

    def test_unknown_lineup_state_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown lineup_state"):
            compute_matchup_fields(
                handedness_matchup="R_vs_R",
                lineup_state="garbage",
            )
