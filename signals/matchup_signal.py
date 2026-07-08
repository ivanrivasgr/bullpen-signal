"""Matchup signal generation.

Implements the per-pitch matchup signal defined in ADR 0016. The
function `generate_matchup_signal` takes a row from silver_matchup_events
and returns a MatchupSignal Pydantic model with:

- signal_value: the matchup edge in the pitcher's direction. Positive
  means advantage pitcher; negative means advantage batter. Magnitudes
  are placeholders keyed on handedness only — they are not calibrated
  against historical outcomes. ADR 0008 established the precedent of
  declared-arbitrary thresholds; this module follows the same pattern.
  Phase 3 built the reconciliation layer that produces correction rates,
  but did not calibrate these magnitudes: the multi-day validation
  (docs/phase3/validation_2026_06_11_multiday.md) showed the rates need
  full-season volume before they support calibration. Calibration is
  therefore deferred to a future data pull, not done in Phase 3.

- confidence_band: one of {full, reduced, suppressed}. Mapped directly
  from lineup_state per ADR 0016: confirmed -> full, uncertain ->
  reduced, projected -> suppressed.

- lineup_state_at_emission: the lineup_state that drove the confidence
  band. Carried on the signal explicitly so Phase 3 reconciliation can
  filter by it without re-joining to the matchup events table.

This module is intentionally pure: no I/O, no logging side effects, no
state. The replay engine calls into it for the batch path. The streaming
Flink job does not call this directly — it calls the Pydantic-free core
in signals.matchup_core, since the Flink runtime has no Pydantic. Both
paths share that core, so they cannot drift (ADR 0021).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from signals.matchup_core import compute_signal_fields


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
    signal_value: float | None = Field(
        default=None,
        description=(
            "Matchup edge in the pitcher's direction. Positive favors "
            "pitcher; negative favors batter. Calibrated from the 2024 "
            "season via the delta method (ADR 0027). NULL when the matchup "
            "is irresolvable -- a player absent from the handedness seed -- "
            "since 'could not compute' is the absence of a value, not 0.0 "
            "(ADR 0028)."
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
    that the replay engine or batch dbt model emits downstream. The
    streaming path does not use this; it calls compute_signal_fields
    directly to avoid a Pydantic dependency in the Flink runtime.

    Required keys in matchup_event:
        event_time, game_pk, at_bat_number, pitch_number,
        pitcher_id, batter_id, lineup_state, handedness_matchup

    handedness_matchup may be None when either side of the matchup is
    unknown. In that case signal_value is None -- an irresolvable matchup
    has no computable value, and is not collapsed to a fabricated 0.0
    (ADR 0028).

    Raises:
        KeyError: if a required field is missing from matchup_event.
        ValueError: if lineup_state is not one of the documented values.
    """
    handedness_matchup = matchup_event.get("handedness_matchup")
    signal_value, confidence_band, lineup_state = compute_signal_fields(
        handedness_matchup=handedness_matchup,
        lineup_state=matchup_event["lineup_state"],
    )

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
