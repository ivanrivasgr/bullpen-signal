"""Pure matchup signal computation — no Pydantic, no I/O, no framework.

This module holds the signal logic that both the batch path and the
streaming path share: the placeholder magnitudes, the confidence-band
mapping, and compute_signal_fields, which turns a handedness matchup and
a lineup state into the three scalar fields the reconciliation layer
compares.

It is deliberately dependency-free (standard library only) so it can be
imported in any runtime. The batch path (signals.matchup_signal) imports
it and wraps the result in a Pydantic MatchupSignal model. The streaming
Flink UDF imports it directly — the Flink container has no Pydantic, and
the signal computation does not need it. Keeping this logic in one place
is the anti-drift guarantee of ADR 0001 and ADR 0021: both paths compute
the signal the same way because they call the same function.

Magnitudes are placeholders keyed on handedness only (ADR 0016). They
are not calibrated against historical outcomes; the multi-day validation
(docs/phase3/validation_2026_06_11_multiday.md) records that calibration
is deferred until a full-season pull provides the volume to support it.
"""

from __future__ import annotations

from typing import Literal

# Placeholder signal values per handedness matchup. Magnitudes are not
# calibrated — they encode the conventional baseball intuition that
# same-side matchups slightly favor the pitcher and opposite-side
# matchups favor the batter. Calibration is deferred pending full-season
# volume (see module docstring).
_PLACEHOLDER_SIGNAL_VALUES: dict[str | None, float] = {
    "R_vs_R": 0.05,
    "R_vs_L": -0.10,
    "L_vs_R": -0.10,
    "L_vs_L": 0.08,
    # Switch-hitters bat from the opposite side of the pitcher, so they
    # effectively get the favorable opposite-side matchup. Same magnitude
    # as L_vs_R / R_vs_L placeholders.
    "R_vs_S": -0.10,
    "L_vs_S": -0.10,
    # Switch-pitchers (very rare) face one batter handedness at a time.
    # We approximate as the favorable matchup for the pitcher.
    "S_vs_R": 0.05,
    "S_vs_L": 0.08,
    "S_vs_S": 0.0,  # extremely rare; both pick optimal -> neutral
    None: 0.0,  # unknown matchup -> neutral signal
}

# Mapping from lineup_state to confidence_band per ADR 0016.
_CONFIDENCE_BAND_BY_LINEUP_STATE: dict[str, Literal["full", "reduced", "suppressed"]] = {
    "confirmed": "full",
    "uncertain": "reduced",
    "projected": "suppressed",
}


def compute_signal_fields(
    handedness_matchup: str | None,
    lineup_state: str,
) -> tuple[float, str, str]:
    """The pure core of the matchup signal: the three scalar fields.

    Returns (signal_value, confidence_band, lineup_state_at_emission).
    No Pydantic dependency — plain dict lookups and a validation check.
    Both the batch path (generate_matchup_signal, which wraps the result
    in a MatchupSignal model) and the streaming path (the Flink UDF, which
    needs Flink-serializable scalars) call this core, so the two paths
    cannot drift and the streaming runtime needs no Pydantic.

    Raises ValueError if lineup_state is not one of the documented values.
    """
    if lineup_state not in _CONFIDENCE_BAND_BY_LINEUP_STATE:
        raise ValueError(
            f"unknown lineup_state {lineup_state!r}; "
            f"expected one of {sorted(_CONFIDENCE_BAND_BY_LINEUP_STATE)}"
        )
    signal_value = _PLACEHOLDER_SIGNAL_VALUES.get(handedness_matchup, 0.0)
    confidence_band = _CONFIDENCE_BAND_BY_LINEUP_STATE[lineup_state]
    return (signal_value, confidence_band, lineup_state)
