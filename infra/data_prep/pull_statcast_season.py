"""Pull the full 2024 regular season from Statcast into monthly parquets.

Day-by-day pull through pybaseball with its on-disk cache enabled (the
same pattern as ingestion/replay_engine/statcast_source.py: first pull
of a day costs ~7-9s against the Statcast endpoint, cached re-pulls are
~0.1s, so interrupting and re-running this script is cheap). One parquet
per month under the output directory; months whose parquet already
exists are skipped, which makes the run resumable at month granularity.

Rows are filtered to regular-season games (game_type = 'R') as a guard:
the season window includes dates that also carried spring-training games
(the Seoul Series opened the regular season on 2024-03-20 while camps
were still playing), and the guard keeps non-regular-season rows out
regardless of endpoint defaults.

Default window: 2024-03-20 (Seoul Series opener) .. 2024-09-30 (the
final regular-season day, including the makeup doubleheader).

Output feeds infra/data_prep/build_matchup_calibration.py; per the
project volume standard (docs/phase3/validation_2026_06_11_multiday.md),
this full-season pull is what gives the calibration magnitudes weight.
"""

from __future__ import annotations

import argparse
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from pybaseball import cache, statcast

# Same idempotent cache enablement as statcast_source.py: without it,
# every day costs a fresh endpoint query on re-runs.
cache.enable()

RETRIES = 3
RETRY_SLEEP_S = 20


def month_days(start: date, end: date) -> dict[str, list[date]]:
    """Group every calendar day in [start, end] by its YYYY_MM key."""
    days_by_month: dict[str, list[date]] = {}
    d = start
    while d <= end:
        days_by_month.setdefault(f"{d.year:04d}_{d.month:02d}", []).append(d)
        d += timedelta(days=1)
    return days_by_month


def pull_day(d: date) -> pd.DataFrame:
    """Pull one day from Statcast, retrying transient endpoint failures."""
    last_error: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        try:
            return statcast(start_dt=d.isoformat(), end_dt=d.isoformat())
        except Exception as exc:
            last_error = exc
            print(f"    attempt {attempt}/{RETRIES} failed: {exc}")
            time.sleep(RETRY_SLEEP_S)
    raise RuntimeError(f"could not pull {d.isoformat()}") from last_error


def build(start: date, end: date, out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    total_rows = 0
    days_with_games = 0
    dropped_non_regular = 0

    for month_key, days in month_days(start, end).items():
        target = out / f"statcast_{month_key}.parquet"
        if target.exists():
            print(f"{target} exists, skipping month")
            continue

        frames: list[pd.DataFrame] = []
        for d in days:
            df = pull_day(d)
            if df is None or df.empty:
                print(f"  {d.isoformat()}: no games")
                continue
            if "game_type" in df.columns:
                before = len(df)
                df = df[df["game_type"] == "R"]
                dropped_non_regular += before - len(df)
            if df.empty:
                print(f"  {d.isoformat()}: no regular-season rows")
                continue
            frames.append(df)
            days_with_games += 1
            print(f"  {d.isoformat()}: {len(df)} pitches")

        if not frames:
            print(f"{month_key}: no rows, no parquet written")
            continue
        month_df = pd.concat(frames, ignore_index=True)
        month_df.to_parquet(target, index=False)
        total_rows += len(month_df)
        print(f"wrote {target} ({len(month_df)} rows)")

    print()
    print(
        f"done: {total_rows} rows across new monthly parquets, "
        f"{days_with_games} days with games, "
        f"{dropped_non_regular} non-regular-season rows dropped"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2024-03-20", help="first day, YYYY-MM-DD")
    parser.add_argument("--end", default="2024-09-30", help="last day, YYYY-MM-DD")
    parser.add_argument("--out-dir", default="data/raw/season_2024")
    args = parser.parse_args()
    build(date.fromisoformat(args.start), date.fromisoformat(args.end), args.out_dir)


if __name__ == "__main__":
    main()
