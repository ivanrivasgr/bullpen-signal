"""Event models for the replay stream.

These are the Python-side representations. The wire format is Avro, defined in
`streaming/schemas/`. Keep them in sync: any field added here needs a matching
Avro schema evolution step.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class PitchEvent(BaseModel):
    """A single pitch as published to `pitches.raw`.

    Field names mirror Statcast where possible. `event_time` is the canonical
    event-time timestamp; `ingest_time` is when the replay engine published it.
    """

    event_time: datetime
    ingest_time: datetime
    game_pk: int
    at_bat_number: int
    pitch_number: int
    inning: int
    inning_topbot: Literal["Top", "Bot"]
    pitcher_id: int
    # batter_id is ALWAYS the observed (ground-truth) batter from Statcast.
    # During the BATTER_UNCERTAIN window (ADR 0014) the system does not yet
    # know this value operationally, but the replay does (it reads historical
    # data), so we preserve it here rather than destroy it. The inference the
    # system would have made at emission time lives in projected_batter_id.
    batter_id: int
    # The projected batter the system would have used during the uncertainty
    # window (ADR 0015). None when lineup_state == "confirmed" (no projection
    # needed) or when projection failed. When lineup_state == "uncertain",
    # this holds the projection and batter_id holds the truth, so downstream
    # reconciliation can compare the two without re-deriving either.
    projected_batter_id: int | None = None
    pitch_type: str | None = None
    release_speed: float | None = None
    release_spin_rate: float | None = None
    plate_x: float | None = None
    plate_z: float | None = None
    zone: int | None = None
    balls: int
    strikes: int
    outs_when_up: int
    on_1b: int | None = None
    on_2b: int | None = None
    on_3b: int | None = None
    description: str | None = None
    events: str | None = None
    home_score: int
    away_score: int
    # Numeric team_ids for the two clubs, threaded so the uncertainty window
    # can infer which team is batting (ADR 0015 projection needs the batting
    # team). Derived from the Statcast home_team/away_team abbreviations via
    # the team_abbreviations reference map. Optional so events built without
    # team context (older tests, hand-built fixtures) still validate.
    home_team_id: int | None = None
    away_team_id: int | None = None
    # Epistemic state of batter identity at emission time. See ADR 0013.
    # One of: "confirmed", "uncertain", "projected". Default keeps historical
    # replay traffic backward-compatible — pre-Phase-2 events implicitly mean confirmed.
    lineup_state: Literal["confirmed", "uncertain", "projected"] = "confirmed"
    # Reserved for the noise injector.
    is_late_arrival: bool = False
    is_duplicate: bool = False
    correction_of: str | None = Field(
        default=None,
        description="If this event is a correction, the pitch_uid it replaces.",
    )


class GameStateEvent(BaseModel):
    """A game-state snapshot published to `game_state.raw`.

    Emitted on inning change, pitching change, pinch-hit, and scoring plays.
    """

    event_time: datetime
    ingest_time: datetime
    game_pk: int
    inning: int
    inning_topbot: Literal["Top", "Bot"]
    home_score: int
    away_score: int
    home_pitcher_id: int | None = None
    away_pitcher_id: int | None = None
    next_batter_id: int | None = None
    event_type: Literal[
        "inning_start",
        "pitching_change",
        "pinch_hit",
        "scoring_play",
        "game_start",
        "game_end",
    ]


class CorrectionEvent(BaseModel):
    """A late-breaking correction to an earlier event.

    Simulates MLB official scoring revisions or Statcast pitch-type reclassification.
    Published to `corrections.cdc` so batch can reconcile and streaming can react.
    """

    event_time: datetime
    ingest_time: datetime
    game_pk: int
    original_pitch_uid: str
    field: str
    old_value: str | None
    new_value: str | None


class MatchupRevisionEvent(BaseModel):
    """A revision of a previously emitted matchup signal.

    ADR 0017 defines the taxonomy. The revision carries both the previous
    and current signal values + confidence bands so downstream consumers
    can compute the delta without re-joining against the original emission.
    """

    event_time: datetime
    ingest_time: datetime
    game_pk: int
    at_bat_number: int
    pitch_number: int
    pitcher_id: int
    batter_id: int
    revision_type: Literal["material_update", "baseline_confirmed", "suppressed_by_governance"]
    previous_signal_value: float
    current_signal_value: float
    previous_confidence_band: Literal["full", "reduced", "suppressed"]
    current_confidence_band: Literal["full", "reduced", "suppressed"]
    source_event_id: str = Field(
        description=(
            "Identifier of the upstream event that triggered the revision — "
            "lineup_confirmation event id, correction_event id, or "
            "reconciliation batch id. Per ADR 0017, the specific cause is "
            "recoverable from this field without inflating the taxonomy."
        ),
    )
