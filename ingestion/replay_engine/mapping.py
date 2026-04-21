"""Turn Statcast DataFrame rows into `PitchEvent` models."""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pandas as pd

from .events import PitchEvent


def row_to_pitch_event(row: pd.Series, ingest_time: datetime) -> PitchEvent:
    """Map one Statcast row to a PitchEvent.

    Null-handling: Statcast uses NaN for missing numerics and empty strings for
    missing categoricals. We coerce both to None so Pydantic sees explicit
    optionals.
    """
    return PitchEvent(
        event_time=row["event_time"].to_pydatetime(),
        ingest_time=ingest_time,
        game_pk=int(row["game_pk"]),
        at_bat_number=int(row["at_bat_number"]),
        pitch_number=int(row["pitch_number"]),
        inning=int(row["inning"]),
        inning_topbot=_top_or_bot(row["inning_topbot"]),
        pitcher_id=int(row["pitcher"]),
        batter_id=int(row["batter"]),
        pitch_type=_str_or_none(row.get("pitch_type")),
        release_speed=_float_or_none(row.get("release_speed")),
        release_spin_rate=_float_or_none(row.get("release_spin_rate")),
        plate_x=_float_or_none(row.get("plate_x")),
        plate_z=_float_or_none(row.get("plate_z")),
        zone=_int_or_none(row.get("zone")),
        balls=int(row["balls"]),
        strikes=int(row["strikes"]),
        outs_when_up=int(row["outs_when_up"]),
        on_1b=_int_or_none(row.get("on_1b")),
        on_2b=_int_or_none(row.get("on_2b")),
        on_3b=_int_or_none(row.get("on_3b")),
        description=_str_or_none(row.get("description")),
        events=_str_or_none(row.get("events")),
        home_score=int(row.get("home_score", 0)),
        away_score=int(row.get("away_score", 0)),
    )


def _top_or_bot(val: str) -> str:
    return "Top" if str(val).lower().startswith("top") else "Bot"


def _float_or_none(val: object) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if math.isnan(f):
        return None
    return f


def _int_or_none(val: object) -> int | None:
    f = _float_or_none(val)
    if f is None:
        return None
    return int(f)


def _str_or_none(val: object) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() == "nan":
        return None
    return s


def now_utc() -> datetime:
    return datetime.now(UTC)
