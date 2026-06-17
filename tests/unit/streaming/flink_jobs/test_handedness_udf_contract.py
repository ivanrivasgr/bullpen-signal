"""Contract test: the streaming handedness derivation must equal dbt's.

silver_matchup_events derives handedness_matchup as
  NULL if either hand is NULL, else pitcher_hand || '_vs_' || batter_hand
over hands in {L, R, S}. The streaming path derives it via
compute_handedness_fields, which calls the shared
derive_handedness_matchup. This asserts the two agree across every
hand combination plus the missing-player cases, so the streaming and
batch handedness matchups cannot drift (ADR 0021).

It does not need a Flink cluster — it exercises the plain functions the
UDF wraps.
"""

from __future__ import annotations

import pytest

from signals.matchup_core import derive_handedness_matchup

_HANDS = ["L", "R", "S", None]


def _dbt_reference(pitcher_hand: str | None, batter_hand: str | None) -> str | None:
    """The dbt CASE, transcribed: NULL if either side NULL, else concat."""
    if pitcher_hand is None or batter_hand is None:
        return None
    return f"{pitcher_hand}_vs_{batter_hand}"


class TestHandednessDerivationMatchesDbt:
    @pytest.mark.parametrize("pitcher_hand", _HANDS)
    @pytest.mark.parametrize("batter_hand", _HANDS)
    def test_derivation_equals_dbt_reference(
        self, pitcher_hand: str | None, batter_hand: str | None
    ) -> None:
        assert derive_handedness_matchup(pitcher_hand, batter_hand) == _dbt_reference(
            pitcher_hand, batter_hand
        )


class TestComputeHandednessFieldsAgainstSeed:
    """compute_handedness_fields resolves real seed players correctly."""

    def test_real_and_projected_matchup(self) -> None:
        from streaming.flink_jobs.matchup.handedness_udf import (
            compute_handedness_fields,
        )

        # 434378 pitcher (R), 444482 batter (L) — verified against the seed.
        real, projected = compute_handedness_fields(434378, 444482, None)
        assert real == "R_vs_L"
        assert projected is None

    def test_missing_player_yields_none(self) -> None:
        from streaming.flink_jobs.matchup.handedness_udf import (
            compute_handedness_fields,
        )

        real, projected = compute_handedness_fields(434378, 999999, None)
        assert real is None
        assert projected is None
