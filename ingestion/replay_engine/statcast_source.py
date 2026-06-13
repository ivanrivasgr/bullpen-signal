"""Load pitch-level data from Statcast for a given date or game.

Uses pybaseball. Caching is enabled at import time via cache.enable(),
which writes to pybaseball's default location (~/.pybaseball/cache).
This makes repeated day-pulls — multi-day replays, re-running the
validation harness — hit the local cache instead of re-querying the
Statcast endpoint. First pull of a day is ~7-9s; cached pulls are
~0.1s. The cache directory is outside the repo and not tracked.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd
import structlog
from pybaseball import cache

# Enable pybaseball's on-disk cache once, at import time. Without this,
# every statcast(day) call re-queries the endpoint (~7-9s each), which
# makes multi-day replays and repeated validation runs slow and brittle
# against the upstream API. Enabled, a day pulled once is served from
# ~/.pybaseball/cache on every subsequent pull (~0.1s, measured ~79x
# faster). Idempotent and safe to call on every import.
cache.enable()

log = structlog.get_logger(__name__)


def load_statcast_date(target_date: date) -> pd.DataFrame:
    """Load every pitch thrown on `target_date`.

    Returns a DataFrame with Statcast columns plus a synthesized `event_time`
    built from `game_date` and `game_pk` ordering. Statcast itself does not
    carry a per-pitch wall-clock timestamp, so we synthesize one that is
    monotonic within a game and ordered by at-bat and pitch number.
    """
    import pybaseball

    date_str = target_date.isoformat()
    log.info("loading statcast", date=date_str)

    df = pybaseball.statcast(start_dt=date_str, end_dt=date_str)
    if df.empty:
        log.warning("no pitches returned", date=date_str)
        return df

    df = df.sort_values(
        ["game_pk", "inning", "inning_topbot", "at_bat_number", "pitch_number"],
        ascending=[True, True, False, True, True],
    ).reset_index(drop=True)

    df["event_time"] = _synthesize_event_times(df)

    log.info(
        "statcast loaded",
        rows=len(df),
        games=df["game_pk"].nunique(),
    )
    return df


def _synthesize_event_times(df: pd.DataFrame) -> pd.Series:
    """Build a monotonic per-game event_time series.

    Statcast rows do not carry per-pitch timestamps. We use the date as the
    base and increment by a realistic pitch cadence (~23 seconds between
    pitches within an at-bat, ~90 seconds between at-bats).
    """
    base = pd.to_datetime(df["game_date"]).dt.tz_localize(UTC)
    # Add an hour so games "start" at 19:00 UTC-ish.
    base = base + pd.Timedelta(hours=19)

    offsets = []
    last_game = None
    last_at_bat = None
    running_offset = pd.Timedelta(seconds=0)
    pitch_gap = pd.Timedelta(seconds=23)
    at_bat_gap = pd.Timedelta(seconds=90)

    for _, row in df.iterrows():
        if row["game_pk"] != last_game:
            running_offset = pd.Timedelta(seconds=0)
            last_game = row["game_pk"]
            last_at_bat = row["at_bat_number"]
        elif row["at_bat_number"] != last_at_bat:
            running_offset += at_bat_gap
            last_at_bat = row["at_bat_number"]
        else:
            running_offset += pitch_gap
        offsets.append(running_offset)

    return base + pd.Series(offsets, index=df.index)


def filter_to_game(df: pd.DataFrame, game_pk: int) -> pd.DataFrame:
    """Filter a full-day DataFrame down to one game."""
    return df[df["game_pk"] == game_pk].reset_index(drop=True).copy()


def list_games_for_date(target_date: date) -> list[int]:
    """List the `game_pk` values that played on `target_date`."""
    df = load_statcast_date(target_date)
    if df.empty:
        return []
    return sorted(df["game_pk"].unique().tolist())


def earliest_game_date(df: pd.DataFrame) -> datetime:
    """Return the earliest synthesized event_time, as a UTC datetime."""
    return df["event_time"].min().to_pydatetime()
