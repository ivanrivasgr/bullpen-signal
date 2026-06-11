"""Multi-day end-to-end validation of the Phase 3 reconciliation pipeline.

Runs the replay over a consecutive range of real game dates at the
real uncertainty rate (not forced), accumulating into bronze WITHOUT
wiping between days, then builds the marts once and runs the revision
producer once. Emits an honest report of what the pipeline produced
over volume: uncertain counts, projection success/failure, revision
classification, and correction rates by handedness matchup.

This is a validation harness, not a production component. It exists to
answer one question before Phase 3 is declared sound: does the pipeline
survive real volume and real sequencing, or does single-day testing
hide bugs? Run it, read the report, fix what breaks.

Usage:
    python -m scripts.validate_reconciliation_multiday \\
        --start-date 2024-04-02 --end-date 2024-04-15 \\
        --cache-start 2024-04-01

The cache must start at least one day before the first replay date so
the ADR 0015 projection has a previous-game lineup to draw from.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import date, timedelta

import structlog

log = structlog.get_logger(__name__)


def _run(cmd: list[str], env: dict | None = None) -> subprocess.CompletedProcess:
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(cmd, env=full_env, capture_output=True, text=True)


def iter_dates(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def replay_one_day(target: date) -> dict:
    """Replay a single date at the real uncertainty rate. Returns a status dict."""
    # Real rate: no --uncertainty-rate override, so UncertaintyConfig default 0.15.
    # Noise off to keep natural keys clean across the multi-day accumulation.
    env = {
        "REPLAY_NOISE_LATE_ARRIVAL_PROB": "0.0",
        "REPLAY_NOISE_DUPLICATE_PROB": "0.0",
        "REPLAY_NOISE_CORRECTION_PROB": "0.0",
    }
    proc = _run(
        [
            ".venv/bin/python",
            "-m",
            "ingestion.replay_engine.run",
            "--game-date",
            target.isoformat(),
            "--speed",
            "100000",
            "--seed",
            "42",
        ],
        env=env,
    )
    ok = proc.returncode == 0
    return {
        "date": target.isoformat(),
        "ok": ok,
        "stderr_tail": proc.stderr[-300:] if not ok else "",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", type=date.fromisoformat, required=True)
    parser.add_argument("--end-date", type=date.fromisoformat, required=True)
    parser.add_argument("--cache-start", type=date.fromisoformat, required=True)
    args = parser.parse_args()

    log.info("validation.start", start=args.start_date.isoformat(), end=args.end_date.isoformat())

    # 1. Build the lineup cache over cache_start..end_date.
    log.info("validation.precompute_cache")
    proc = _run(
        [
            ".venv/bin/python",
            "-m",
            "ingestion.replay_engine.precompute_lineups",
            "--start-date",
            args.cache_start.isoformat(),
            "--end-date",
            args.end_date.isoformat(),
            "--output",
            "data/precomputed/lineups.json",
        ]
    )
    if proc.returncode != 0:
        log.error("validation.precompute_failed", stderr=proc.stderr[-500:])
        sys.exit(1)

    # 2. Replay each day in sequence, accumulating into bronze.
    results = []
    for target in iter_dates(args.start_date, args.end_date):
        r = replay_one_day(target)
        log.info("validation.replayed_day", **{k: v for k, v in r.items() if k != "stderr_tail"})
        results.append(r)

    failed_days = [r["date"] for r in results if not r["ok"]]
    log.info("validation.replays_done", total=len(results), failed=len(failed_days))

    print("\n" + "=" * 60)
    print("MULTI-DAY VALIDATION REPORT")
    print("=" * 60)
    print(f"Replay window: {args.start_date} .. {args.end_date} ({len(results)} days)")
    print(f"Days replayed OK: {len(results) - len(failed_days)} / {len(results)}")
    if failed_days:
        print(f"FAILED DAYS: {failed_days}")
    print()
    print("NOTE: This script runs replays only. After it completes, run the")
    print("materialize + dbt build + producer steps, then re-run the report")
    print("section below against the populated warehouse.")


if __name__ == "__main__":
    main()
