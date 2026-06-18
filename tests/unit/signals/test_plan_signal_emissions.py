"""Tests for plan_signal_emissions — the shared emission expansion.

silver_matchup_signals (batch) and the future streaming job both call
plan_signal_emissions to decide how many signals a pitch emits and from
which handedness matchup + lineup_state. These tests pin the three cases
of the ADR 0020 emission model so the two paths cannot drift.
"""

from __future__ import annotations

from signals.matchup_core import plan_signal_emissions


class TestEmissionExpansion:
    def test_uncertain_with_projection_emits_reduced_then_full(self) -> None:
        emissions = plan_signal_emissions(
            lineup_state="uncertain",
            handedness_matchup="R_vs_L",
            projected_handedness_matchup="R_vs_R",
            has_projection=True,
        )
        # Reduced first (projected matchup, uncertain), then full (real, confirmed).
        assert emissions == [("R_vs_R", "uncertain"), ("R_vs_L", "confirmed")]

    def test_uncertain_without_projection_emits_single_uncertain(self) -> None:
        emissions = plan_signal_emissions(
            lineup_state="uncertain",
            handedness_matchup="R_vs_L",
            projected_handedness_matchup=None,
            has_projection=False,
        )
        # Single emission, real matchup, still uncertain (honest reduced band).
        assert emissions == [("R_vs_L", "uncertain")]

    def test_confirmed_emits_single_full(self) -> None:
        emissions = plan_signal_emissions(
            lineup_state="confirmed",
            handedness_matchup="R_vs_L",
            projected_handedness_matchup=None,
            has_projection=False,
        )
        assert emissions == [("R_vs_L", "confirmed")]

    def test_reduced_emission_uses_projected_matchup_not_real(self) -> None:
        # The reduced signal must reflect what the system knew during the
        # window — the projected matchup — not the real one (ADR 0020).
        emissions = plan_signal_emissions(
            lineup_state="uncertain",
            handedness_matchup="L_vs_L",
            projected_handedness_matchup="L_vs_R",
            has_projection=True,
        )
        reduced_matchup, reduced_state = emissions[0]
        assert reduced_matchup == "L_vs_R"
        assert reduced_state == "uncertain"

    def test_null_matchup_propagates(self) -> None:
        # A None matchup (player absent from seed) flows through unchanged;
        # compute_signal_fields turns it into the neutral signal.
        emissions = plan_signal_emissions(
            lineup_state="confirmed",
            handedness_matchup=None,
            projected_handedness_matchup=None,
            has_projection=False,
        )
        assert emissions == [(None, "confirmed")]
