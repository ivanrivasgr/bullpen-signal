"""Matchup signal generation.

Implements the per-pitch matchup signal defined in ADR 0016. The
function `generate_matchup_signal` takes a row from silver_matchup_events
and returns a MatchupSignal Pydantic model with:

- signal_value: the matchup edge in the pitcher's direction. Positive
  means advantage pitcher; negative means advantage batter. Magnitudes
  are placeholders calibrated against handedness only — they are not
  calibrated against historical outcomes yet. ADR 0008 established the
  precedent of declared-arbitrary thresholds; this module follows the
  same pattern and will be replaced with calibrated values in Phase 3
  once the reconciliation layer produces correction-rate data.

- confidence_band: one of {full, reduced, suppressed}. Mapped directly
  from lineup_state per ADR 0016: confirmed -> full, uncertain ->
  reduced, projected -> suppressed.

- lineup_state_at_emission: the lineup_state that drove the confidence
  band. Carried on the signal explicitly so Phase 3 reconciliation can
  filter by it without re-joining to the matchup events table.

This module is intentionally pure: no I/O, no logging side effects, no
state. The replay engine and the future Flink job both call into it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# Placeholder signal values per handedness matchup. Magnitudes are not
# calibrated — they encode the conventional baseball intuition that
# same-side matchups slightly favor the pitcher and opposite-side
# matchups favor the batter. Phase 3 will replace these with calibrated
# values from the reconciliation layer.
_PLACEHOLDER_SIGNAL_VALUES: dict[str | None, float] = {
    "R_vs_R": 0.05,
    "R_vs_L": -0.10,
    "L_vs_R": -0.10,
    "L_vs_L": 0.08,
    None: 0.0,  # unknown matchup -> neutral signal
}

# Mapping from lineup_state to confidence_band per ADR 0016.
_CONFIDENCE_BAND_BY_LINEUP_STATE: dict[str, Literal["full", "reduced", "suppressed"]] = {
    "confirmed": "full",
    "uncertain": "reduced",
    "projected": "suppressed",
}


class MatchupSignal(BaseModel):
    """The output of generate_matchup_signal.

    Field names mirror silver_matchup_events for joinability downstream.
    """

    event_time: datetime
    game_pk: int
    at_bat_number: int
    pitch_number: int
    pitcher_id: int
    batter_id: int

    handedness_matchup: str | None = Field(
        default=None,
        description=(
            "The handedness matchup that drove the signal value, e.g. "
            "'R_vs_L'. NULL when either side of the matchup is unknown."
        ),
    )
    signal_value: float = Field(
        description=(
            "Matchup edge in the pitcher's direction. Positive favors "
            "pitcher; negative favors batter. Placeholder values, not "
            "calibrated against outcomes (see module docstring)."
        ),
    )
    confidence_band: Literal["full", "reduced", "suppressed"] = Field(
        description=(
            "Mapped from lineup_state per ADR 0016. 'full' for confirmed "
            "lineups, 'reduced' for uncertain, 'suppressed' for projected. "
            "Suppressed signals are emitted for Phase 3 reconciliation but "
            "should not drive live decisions."
        ),
    )
    lineup_state_at_emission: Literal["confirmed", "uncertain", "projected"] = Field(
        description=(
            "The lineup_state value at signal emission time. Carried "
            "explicitly so Phase 3 can filter without re-joining."
        ),
    )


def generate_matchup_signal(matchup_event: dict) -> MatchupSignal:
    """Build a MatchupSignal from one silver_matchup_events row.

    The input is a dict matching the silver_matchup_events schema. The
    function is pure — no I/O, no logging. It returns a Pydantic model
    that the replay engine or Flink job will emit downstream.

    Required keys in matchup_event:
        event_time, game_pk, at_bat_number, pitch_number,
        pitcher_id, batter_id, lineup_state, handedness_matchup

    handedness_matchup may be None when either side of the matchup is
    unknown. signal_value falls back to the None entry in the placeholder
    table (currently 0.0) in that case.

    Raises:
        KeyError: if a required field is missing from matchup_event.
        ValueError: if lineup_state is not one of the documented values.
    """
    lineup_state = matchup_event["lineup_state"]
    if lineup_state not in _CONFIDENCE_BAND_BY_LINEUP_STATE:
        raise ValueError(
            f"unknown lineup_state {lineup_state!r}; "
            f"expected one of {sorted(_CONFIDENCE_BAND_BY_LINEUP_STATE)}"
        )

    handedness_matchup = matchup_event.get("handedness_matchup")
    signal_value = _PLACEHOLDER_SIGNAL_VALUES.get(handedness_matchup, 0.0)
    confidence_band = _CONFIDENCE_BAND_BY_LINEUP_STATE[lineup_state]

    return MatchupSignal(
        event_time=matchup_event["event_time"],
        game_pk=matchup_event["game_pk"],
        at_bat_number=matchup_event["at_bat_number"],
        pitch_number=matchup_event["pitch_number"],
        pitcher_id=matchup_event["pitcher_id"],
        batter_id=matchup_event["batter_id"],
        handedness_matchup=handedness_matchup,
        signal_value=signal_value,
        confidence_band=confidence_band,
        lineup_state_at_emission=lineup_state,
    )
