"""Precompute lineups for a range of games and write them to the cache.

This is the only place at the replay-engine layer where StatsAPI is
called. The replay engine itself reads from the cache produced here, so
runtime is deterministic and StatsAPI availability does not affect
replay reproducibility.

Run as a module:

    python -m ingestion.replay_engine.precompute_lineups \\
        --start-date 2024-04-01 \\
        --end-date 2024-04-15 \\
        --output data/precomputed/lineups.json

The cache file is gitignored and regenerated per replay range.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import structlog

from ingestion.replay_engine.lineup_projection import DEFAULT_CACHE_PATH
from ingestion.replay_engine.statsapi_source import load_lineups

log = structlog.get_logger(__name__)


def _iter_dates(start_date: date, end_date: date):
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def _list_game_pks_on(target_date: date) -> list[tuple[int, int, int]]:
    """Return a list of (game_pk, home_team_id, away_team_id) for a given date.

    Uses StatsAPI's schedule endpoint. Returns empty list on any failure
    rather than raising, so the precompute step is best-effort across the
    range.
    """
    try:
        import statsapi
    except ImportError:
        log.warning("statsapi not installed; skipping schedule")
        return []
    try:
        schedule = statsapi.schedule(date=target_date.isoformat())
    except Exception as exc:
        log.warning(
            "statsapi schedule failed",
            target_date=target_date.isoformat(),
            error=str(exc),
        )
        return []

    games = []
    for entry in schedule:
        game_pk = entry.get("game_id")
        home_team_id = entry.get("home_id")
        away_team_id = entry.get("away_id")
        if game_pk is None or home_team_id is None or away_team_id is None:
            continue
        games.append((int(game_pk), int(home_team_id), int(away_team_id)))
    return games


def precompute(
    start_date: date,
    end_date: date,
    output_path: Path,
) -> None:
    """Build the lineup cache for every game from start_date through end_date inclusive."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    records: list[dict] = []
    for target_date in _iter_dates(start_date, end_date):
        games = _list_game_pks_on(target_date)
        log.info(
            "precompute.processing_date",
            date=target_date.isoformat(),
            n_games=len(games),
        )
        for game_pk, home_team_id, away_team_id in games:
            lineups = load_lineups(game_pk)
            for side, team_id in (("home", home_team_id), ("away", away_team_id)):
                batting_order = lineups.get(side, [])
                records.append(
                    {
                        "game_pk": game_pk,
                        "game_date": target_date.isoformat(),
                        "team_id": team_id,
                        "side": side,
                        "batting_order": list(batting_order),
                    }
                )

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "lineups": records,
    }
    with output_path.open("w") as f:
        json.dump(payload, f, indent=2)
    log.info(
        "precompute.written",
        output=str(output_path),
        records=len(records),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Precompute lineups for a range of games into the replay engine cache.",
    )
    parser.add_argument(
        "--start-date",
        required=True,
        type=lambda s: date.fromisoformat(s),
        help="Start date in YYYY-MM-DD format (inclusive).",
    )
    parser.add_argument(
        "--end-date",
        required=True,
        type=lambda s: date.fromisoformat(s),
        help="End date in YYYY-MM-DD format (inclusive).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_CACHE_PATH,
        help=f"Output cache path. Default: {DEFAULT_CACHE_PATH}",
    )
    args = parser.parse_args()
    precompute(args.start_date, args.end_date, args.output)


if __name__ == "__main__":
    main()
