"""Build dbt/seeds/player_names.csv from the Chadwick Bureau register.

Downloads the public register (github.com/chadwickbureau/register), filters to
the player ids present in this project's data (their MLBAM ids, which are the
pitcher_id / batter_id values in silver_pitch_events), and writes a seed mapping
each id to its real name. Source: Chadwick Bureau, public register, used for
non-commercial analysis with attribution.
"""

from __future__ import annotations

import csv
import os
import urllib.request

import duckdb

REGISTER_BASE = "https://raw.githubusercontent.com/chadwickbureau/register/master/data"
HEX = "0123456789abcdef"
DB = os.path.expanduser("~/.bullpen/dbt.duckdb")
OUT = "dbt/seeds/player_names.csv"


def player_ids_from_data() -> set[int]:
    con = duckdb.connect(DB, read_only=True)
    rows = con.execute(
        """
        SELECT DISTINCT player_id FROM (
            SELECT pitcher_id AS player_id FROM silver.silver_pitch_events
            UNION SELECT batter_id FROM silver.silver_pitch_events
            UNION SELECT projected_batter_id FROM silver.silver_pitch_events
                  WHERE projected_batter_id IS NOT NULL
        ) WHERE player_id IS NOT NULL
        """
    ).fetchall()
    con.close()
    return {int(r[0]) for r in rows}


def build():
    want = player_ids_from_data()
    print(f"player ids to resolve: {len(want)}")

    found: dict[int, tuple[str, str]] = {}
    for h in HEX:
        url = f"{REGISTER_BASE}/people-{h}.csv"
        print(f"  scanning people-{h}.csv ...")
        with urllib.request.urlopen(url) as resp:
            text = resp.read().decode("utf-8")
        reader = csv.DictReader(text.splitlines())
        for row in reader:
            mlbam = row.get("key_mlbam", "").strip()
            if not mlbam:
                continue
            try:
                mid = int(mlbam)
            except ValueError:
                continue
            if mid in want and mid not in found:
                found[mid] = (row.get("name_last", "").strip(), row.get("name_first", "").strip())

    print(f"resolved: {len(found)} of {len(want)}")
    missing = want - set(found)
    if missing:
        print(f"unresolved ids (no Chadwick match): {len(missing)}")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["player_id", "name_last", "name_first"])
        for mid in sorted(want):
            last, first = found.get(mid, ("", ""))
            w.writerow([mid, last, first])
    print(f"wrote {OUT} ({len(want)} rows; unresolved have empty names, not fabricated)")


if __name__ == "__main__":
    build()
