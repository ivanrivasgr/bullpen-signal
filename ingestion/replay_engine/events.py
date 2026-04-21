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
    batter_id: int
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
