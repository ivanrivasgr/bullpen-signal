"""Load the player_handedness seed into an in-memory lookup.

The seed at dbt/seeds/player_handedness.csv maps (player_id, role) to a
hand ('L', 'R', or 'S'). It is the same seed the batch path joins in
silver_matchup_events; loading it here lets the streaming matchup job
resolve handedness for a pitch's pitcher and batter without a join
against an external table.

The seed is small (about 1200 rows) and static within a process — a
player's handedness does not change — so it is loaded once, cached at
module level, and safe to broadcast into a Flink job. Because handedness
is static, this lookup does not violate the point-in-time honesty the
streaming path requires (ADR 0021): knowing a batter is left-handed is
not knowledge of the future.

The (player_id, role) key matches the seed's grain. A player can appear
as both a pitcher and a batter (e.g. two-way players, or pitchers who
bat), so role disambiguates which hand applies in a given lookup.
"""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

# signals/handedness_lookup.py -> repo root -> dbt/seeds/...
_SEED_CSV = Path(__file__).resolve().parents[1] / "dbt" / "seeds" / "player_handedness.csv"


@lru_cache(maxsize=1)
def load_handedness_map() -> dict[tuple[int, str], str]:
    """Return a dict mapping (player_id, role) -> hand ('L'/'R'/'S').

    Cached for the process lifetime. Raises FileNotFoundError if the seed
    is missing, since the matchup job cannot resolve handedness without it.
    """
    if not _SEED_CSV.exists():
        raise FileNotFoundError(
            f"Handedness seed not found at {_SEED_CSV}. It ships with the repo under dbt/seeds/."
        )
    mapping: dict[tuple[int, str], str] = {}
    with _SEED_CSV.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            mapping[(int(row["player_id"]), row["role"])] = row["hand"]
    return mapping


def lookup_hand(player_id: int | None, role: str) -> str | None:
    """Look up a player's hand for a given role, or None if absent.

    Returns None when player_id is None (e.g. no projected batter) or when
    the (player_id, role) pair is not in the seed — the same graceful
    degradation the dbt LEFT JOIN produces, where a missing player yields
    NULL handedness and therefore a NULL matchup.
    """
    if player_id is None:
        return None
    return load_handedness_map().get((player_id, role))
