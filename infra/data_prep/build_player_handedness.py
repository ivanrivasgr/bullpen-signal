"""Rebuild dbt/seeds/player_handedness.csv from Statcast parquets.

Derives the static handedness lookup per player and role that the seed
documents: pitchers and batters get separate rows so two-way players can
carry different throwing and batting hands. Batting hand is observational
per the existing seed convention -- a batter seen standing on both sides
is a switch hitter ('S'); pitchers likewise from p_throws. Source data:
the Statcast pitch-level parquets passed on the command line (game-type
filtering is the puller's concern; data/raw/season_2024 already carries
regular-season rows only).

The report compares the rebuilt seed against the existing file, if any:
added players, removed players, and hand reclassifications. Because a
smaller window is a subset of a larger one, valid reclassifications only
move toward 'S' (more data reveals the other side); any move away from
'S' or any removed player signals inconsistent inputs, and the report
flags it so the result is not committed without a look.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

import duckdb

DEFAULT_OUT = "dbt/seeds/player_handedness.csv"

QUERY = """
WITH batters AS (
    SELECT
        CAST(batter AS BIGINT) AS player_id,
        'batter' AS role,
        CASE WHEN COUNT(DISTINCT stand) > 1 THEN 'S' ELSE MAX(stand) END AS hand
    FROM read_parquet({parquets})
    WHERE stand IN ('L', 'R')
    GROUP BY player_id
),

pitchers AS (
    SELECT
        CAST(pitcher AS BIGINT) AS player_id,
        'pitcher' AS role,
        CASE WHEN COUNT(DISTINCT p_throws) > 1 THEN 'S' ELSE MAX(p_throws) END AS hand
    FROM read_parquet({parquets})
    WHERE p_throws IN ('L', 'R')
    GROUP BY player_id
)

SELECT player_id, role, hand FROM batters
UNION ALL
SELECT player_id, role, hand FROM pitchers
ORDER BY role, player_id
"""


def _sql_literal(path: str) -> str:
    return "'" + path.replace("'", "''") + "'"


def _sql_path_list(paths: list[str]) -> str:
    return "[" + ", ".join(_sql_literal(p) for p in paths) + "]"


def build(parquet_paths: list[str], out_path: str) -> None:
    for p in parquet_paths:
        if not Path(p).exists():
            raise SystemExit(f"missing input: {p}")

    con = duckdb.connect()
    rows = con.execute(QUERY.format(parquets=_sql_path_list(parquet_paths))).fetchall()
    con.close()
    rows = [(int(pid), role, hand) for pid, role, hand in rows]

    out = Path(out_path)
    old: dict[tuple[int, str], str] = {}
    if out.exists():
        with out.open(newline="") as f:
            for r in csv.DictReader(f):
                old[(int(r["player_id"]), r["role"])] = r["hand"]

    new = {(pid, role): hand for pid, role, hand in rows}
    added = sorted(k for k in new if k not in old)
    removed = sorted(k for k in old if k not in new)
    changed = sorted((k, old[k], new[k]) for k in new if k in old and old[k] != new[k])

    counts = Counter((role, hand) for _, role, hand in rows)
    print(f"input: {len(parquet_paths)} parquet file(s)")
    for role in ("batter", "pitcher"):
        by_hand = ", ".join(f"{h} {counts[(role, h)]}" for h in ("L", "R", "S"))
        total = sum(counts[(role, h)] for h in ("L", "R", "S"))
        print(f"{role}s: {total} ({by_hand})")

    if old:
        added_roles = Counter(role for _, role in added)
        print(
            f"vs existing seed: +{len(added)} added "
            f"({added_roles['batter']} batters, {added_roles['pitcher']} pitchers), "
            f"{len(removed)} removed, {len(changed)} hand changes"
        )
        for (pid, role), old_hand, new_hand in changed:
            print(f"  changed: {pid} ({role}): {old_hand} -> {new_hand}")
        if removed:
            print("WARNING: removed players -- the input window is smaller than the")
            print("previous seed's; look before committing. Removed:")
            for pid, role in removed[:20]:
                print(f"  removed: {pid} ({role})")
        suspicious = [c for c in changed if c[2] != "S"]
        if suspicious:
            print("WARNING: hand changes moving away from 'S' contradict window")
            print("containment; look before committing.")
    else:
        print("no existing seed found; writing fresh")

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["player_id", "role", "hand"])
        w.writerows(rows)
    print(f"wrote {out_path} ({len(rows)} rows)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--parquet", nargs="+", required=True, help="Statcast parquet path(s) to derive from"
    )
    parser.add_argument("--out", default=DEFAULT_OUT)
    args = parser.parse_args()
    build(args.parquet, args.out)


if __name__ == "__main__":
    main()
