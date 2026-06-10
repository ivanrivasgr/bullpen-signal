"""Generate the team_id <-> Statcast abbreviation reference map.

The replay engine needs to convert the home_team / away_team
abbreviations Statcast records (e.g. "LAD", "AZ") into the numeric
team_id the lineup cache and StatsAPI use (e.g. 119, 109). This map
is the bridge.

Statcast abbreviations are NOT identical to StatsAPI fileCodes. Four
teams differ: StatsAPI says ANA/ARI/LA/WAS where Statcast writes
LAA/AZ/LAD/WSH. Hand-typing the map or trusting StatsAPI fileCode
would silently break the join for those four teams — all large-market
clubs whose games would then drop out of the reconciliation ledger.

To avoid that, the map is derived from observed game data, not typed
and not taken from StatsAPI. The lineup cache carries (game_pk, side)
-> team_id. The Statcast parquet carries game_pk -> (home_team,
away_team) abbreviations. Joining the two on (game_pk, side) yields
team_id -> abbreviation straight from the games themselves. The
correspondence is whatever actually appeared together in the same
game, which is the most honest source available.

Run as a module to regenerate the CSV:
    python -m ingestion.replay_engine.build_team_abbreviation_map \\
        --cache data/precomputed/lineups.json \\
        --parquet-glob 'data/raw/statcast_2024_*.parquet' \\
        --output ingestion/replay_engine/reference/team_abbreviations.csv

The output is committed to the repo. Regenerate only when the team set
changes (expansion, relocation) or when a new season's Statcast data
introduces a different abbreviation.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import duckdb
import structlog

log = structlog.get_logger(__name__)


def derive_map(cache_path: Path, parquet_glob: str) -> dict[int, str]:
    """Derive team_id -> abbreviation by joining the cache and parquet on (game_pk, side).

    Raises ValueError if any team_id maps to more than one abbreviation,
    which would indicate inconsistent source data.
    """
    payload = json.loads(cache_path.read_text())
    cache_pairs: dict[tuple[int, str], int] = {}
    for record in payload["lineups"]:
        cache_pairs[(record["game_pk"], record["side"])] = record["team_id"]

    con = duckdb.connect()
    rows = con.execute(
        f"""
        SELECT DISTINCT game_pk, home_team, away_team
        FROM read_parquet('{parquet_glob}')
        """
    ).fetchall()
    parquet_map: dict[int, dict[str, str]] = {}
    for game_pk, home, away in rows:
        parquet_map[game_pk] = {"home": home, "away": away}

    team_id_to_abbrs: dict[int, set[str]] = {}
    for (game_pk, side), team_id in cache_pairs.items():
        if game_pk in parquet_map:
            abbr = parquet_map[game_pk][side]
            team_id_to_abbrs.setdefault(team_id, set()).add(abbr)

    result: dict[int, str] = {}
    conflicts: list[tuple[int, set[str]]] = []
    for team_id, abbrs in team_id_to_abbrs.items():
        if len(abbrs) == 1:
            result[team_id] = next(iter(abbrs))
        else:
            conflicts.append((team_id, abbrs))

    if conflicts:
        raise ValueError(f"team_id mapped to multiple abbreviations: {conflicts}")

    return dict(sorted(result.items()))


def write_csv(mapping: dict[int, str], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["team_id", "abbreviation"])
        for team_id, abbr in mapping.items():
            writer.writerow([team_id, abbr])
    log.info("team_abbreviation_map.written", output=str(output_path), teams=len(mapping))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--parquet-glob", type=str, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    mapping = derive_map(args.cache, args.parquet_glob)
    if len(mapping) != 30:
        log.warning("team_abbreviation_map.incomplete", teams=len(mapping), expected=30)
    write_csv(mapping, args.output)


if __name__ == "__main__":
    main()
