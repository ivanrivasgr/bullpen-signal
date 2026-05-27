"""Compute projected batter during the BATTER_UNCERTAIN window.

Implements ADR 0015. The replay engine emits pitch events with
`lineup_state = uncertain` during the synthetic uncertainty window before
lineup confirmation. This module provides the projection that fills
`batter_id` during that window.

Design constraints from earlier ADRs:

- Deterministic (ADR 0014). Two replay runs with the same configuration
  must produce identical projections. We achieve this by reading from a
  precomputed JSON cache rather than calling StatsAPI at runtime.
- Statcast-only at runtime (ADR 0015). The cache is produced offline by
  `precompute_lineups.py`, which is the only place StatsAPI is allowed.
- Hierarchical lookup (ADR 0015). Previous game → walk back to last
  played game → opening day fallback. An injured-list exception filter
  is documented but deferred to a follow-up commit (see below).

This module is a pure function over precomputed inputs. State lives in
the cache file, not in this module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

import structlog

log = structlog.get_logger(__name__)

DEFAULT_CACHE_PATH = Path("data/precomputed/lineups.json")

# How many days back to walk before giving up and falling through to the
# opening-day fallback. Captures off days, doubleheaders moved, and short
# postponements without permitting unbounded lookback.
MAX_WALKBACK_DAYS = 14

TeamSide = Literal["home", "away"]


@dataclass(frozen=True)
class LineupKey:
    """Identifies a single team's lineup for a single game."""

    game_pk: int
    side: TeamSide


@dataclass(frozen=True)
class GameLineup:
    """A team's batting order for a specific game.

    `batting_order` is a list of player IDs in lineup position 1 through 9
    (or however many positions the source provided). Empty list means the
    lineup was not available in the source data.
    """

    game_pk: int
    game_date: date
    team_id: int
    side: TeamSide
    batting_order: list[int]


class LineupCache:
    """Read-only view over the precomputed lineups cache.

    The cache is built once by `precompute_lineups.py` and read many times
    by the replay engine. This class is the only runtime path that touches
    the cache file.

    Cache JSON shape (one record per team per game):

        {
            "lineups": [
                {
                    "game_pk": 745123,
                    "game_date": "2024-04-15",
                    "team_id": 119,
                    "side": "home",
                    "batting_order": [605400, 660271, ...]
                },
                ...
            ]
        }
    """

    def __init__(self, cache_path: Path = DEFAULT_CACHE_PATH) -> None:
        self._cache_path = cache_path
        self._by_team_date: dict[tuple[int, date], GameLineup] = {}
        self._opening_day_by_team: dict[int, GameLineup] = {}
        self._loaded = False

    def load(self) -> None:
        """Read the cache file into memory. Idempotent."""
        if self._loaded:
            return
        if not self._cache_path.exists():
            raise FileNotFoundError(
                f"Lineup cache not found at {self._cache_path}. "
                f"Run `python -m ingestion.replay_engine.precompute_lineups` first."
            )
        with self._cache_path.open() as f:
            raw = json.load(f)

        # Build (team_id, game_date) -> GameLineup index and opening-day index.
        # Opening day is the earliest game_date per team in the cache.
        earliest_by_team: dict[int, date] = {}
        for record in raw.get("lineups", []):
            lineup = GameLineup(
                game_pk=record["game_pk"],
                game_date=date.fromisoformat(record["game_date"]),
                team_id=record["team_id"],
                side=record["side"],
                batting_order=list(record["batting_order"]),
            )
            self._by_team_date[(lineup.team_id, lineup.game_date)] = lineup
            if (
                lineup.team_id not in earliest_by_team
                or lineup.game_date < earliest_by_team[lineup.team_id]
            ):
                earliest_by_team[lineup.team_id] = lineup.game_date
                self._opening_day_by_team[lineup.team_id] = lineup

        self._loaded = True
        log.info(
            "lineup_cache.loaded",
            path=str(self._cache_path),
            team_games=len(self._by_team_date),
            teams_with_opening_day=len(self._opening_day_by_team),
        )

    def get_for_team_on_date(self, team_id: int, game_date: date) -> GameLineup | None:
        """Return the lineup for a team on a specific date, or None if absent."""
        self.load()
        return self._by_team_date.get((team_id, game_date))

    def get_opening_day_for_team(self, team_id: int) -> GameLineup | None:
        """Return the earliest available lineup for a team across the cache."""
        self.load()
        return self._opening_day_by_team.get(team_id)


def compute_projected_batter(
    team_id: int,
    lineup_position: int,
    projection_date: date,
    cache: LineupCache,
) -> int | None:
    """Project the batter at `lineup_position` for `team_id` on `projection_date`.

    Implements the ADR 0015 hierarchy:

    1. Primary — Previous game lineup. The lineup from the team's most
       recent game on (projection_date - 1 day).
    2. Fallback 1 — Last played game. If no game was played the previous
       day (off day, scheduled rest, postponement), walk backward up to
       MAX_WALKBACK_DAYS days until a game is found.
    3. Fallback 2 — Opening day lineup. If no prior game exists in the
       cache for this team, use the earliest available lineup.

    Returns the projected `batter_id`, or None if no lineup could be
    resolved at all (cache miss across every layer).

    `lineup_position` is 1-indexed (1 = leadoff, 9 = ninth in the order).

    INJURED-LIST FILTER (ADR 0015) NOT YET IMPLEMENTED.
    Historical IL status by date is not exposed by StatsAPI in a form the
    precompute step can consume reliably. This function returns the raw
    projected batter without the IL exception. The IL filter will land in
    a follow-up commit once a stable historical IL source is integrated.
    Phase 3 reconciliation should treat this as a documented known gap
    rather than a bug.
    """
    # Layer 1 + 2: walk back from previous day up to MAX_WALKBACK_DAYS.
    for days_back in range(1, MAX_WALKBACK_DAYS + 1):
        candidate_date = projection_date - timedelta(days=days_back)
        lineup = cache.get_for_team_on_date(team_id, candidate_date)
        if lineup is not None and lineup.batting_order:
            return _batter_at_position(lineup, lineup_position)

    # Layer 3: opening day fallback for early-season cases.
    # Only use opening day if it is itself earlier than projection_date.
    # If the projection is for opening day itself or before, the cache
    # has no honest answer.
    opening_day = cache.get_opening_day_for_team(team_id)
    if (
        opening_day is not None
        and opening_day.batting_order
        and opening_day.game_date < projection_date
    ):
        return _batter_at_position(opening_day, lineup_position)

    log.warning(
        "lineup_projection.no_lineup_found",
        team_id=team_id,
        lineup_position=lineup_position,
        projection_date=projection_date.isoformat(),
    )
    return None


def _batter_at_position(lineup: GameLineup, lineup_position: int) -> int | None:
    """Return the batter at the requested position, or None if out of range."""
    if lineup_position < 1 or lineup_position > len(lineup.batting_order):
        return None
    return lineup.batting_order[lineup_position - 1]
