"""Contract test: the streaming emission expansion equals the batch loop.

silver_matchup_signals (batch) expands each pitch by calling
plan_signal_emissions then compute_signal_fields. compute_emission_rows
(streaming) calls the exact same two functions in the same order. This
asserts they produce identical rows across the three emission cases, so
the streaming UDTF and the batch model cannot drift (ADR 0021).

No Flink cluster needed — it exercises the plain generator the UDTF wraps.
"""

from __future__ import annotations

from signals.matchup_core import compute_signal_fields, plan_signal_emissions
from streaming.flink_jobs.matchup.emission_udtf import compute_emission_rows


def _batch_reference(
    lineup_state, handedness_matchup, projected_handedness_matchup, has_projection
):
    """The batch loop, transcribed: plan then compute, in order."""
    emissions = plan_signal_emissions(
        lineup_state=lineup_state,
        handedness_matchup=handedness_matchup,
        projected_handedness_matchup=projected_handedness_matchup,
        has_projection=has_projection,
    )
    return [compute_signal_fields(m, s) for m, s in emissions]


class TestEmissionExpansionEqualsBatch:
    def test_uncertain_with_projection_two_rows(self):
        args = ("uncertain", "R_vs_L", "R_vs_R", True)
        assert list(compute_emission_rows(*args)) == _batch_reference(*args)

    def test_confirmed_one_row(self):
        args = ("confirmed", "R_vs_L", None, False)
        assert list(compute_emission_rows(*args)) == _batch_reference(*args)

    def test_uncertain_without_projection_one_row(self):
        args = ("uncertain", "R_vs_L", None, False)
        assert list(compute_emission_rows(*args)) == _batch_reference(*args)

    def test_reduced_row_uses_projected_handedness(self):
        # The first (reduced) row's value must come from the projected
        # matchup, not the real one — the heart of ADR 0020.
        rows = list(compute_emission_rows("uncertain", "L_vs_L", "L_vs_R", True))
        assert len(rows) == 2
        # L_vs_R calibrated is -0.0097; L_vs_L is +0.0187. Reduced must be L_vs_R's.
        assert rows[0][0] == -0.0097
        assert rows[0][1] == "reduced"
        assert rows[1][0] == 0.0187
        assert rows[1][1] == "full"

    def test_null_matchup_yields_neutral(self):
        rows = list(compute_emission_rows("confirmed", None, None, False))
        assert rows == [(0.0, "full", "confirmed")]
