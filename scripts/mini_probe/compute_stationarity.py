"""
Compute stationarity metrics for the mini-probe sent to Chad Corwin.

Replicates fatigue_bucket logic from dbt/models/silver/silver_pitcher_game_fatigue.sql
exactly:
    CASE WHEN pitch_count < 25 THEN 'low'
         WHEN pitch_count < 50 THEN 'medium'
         ELSE 'high'
    END

Outputs 4 CSVs to --output-dir and prints 3 markdown-ready tables to stdout.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Threshold logic — exact replica of the SQL CASE WHEN
# ---------------------------------------------------------------------------


def classify_bucket(pitch_count: int) -> str:
    if pitch_count < 25:
        return "low"
    if pitch_count < 50:
        return "medium"
    return "high"


# ---------------------------------------------------------------------------
# Per-game aggregation
# ---------------------------------------------------------------------------


def build_per_game_df(raw: pd.DataFrame) -> pd.DataFrame:
    agg = (
        raw.groupby(["game_pk", "pitcher"], as_index=False)
        .size()
        .rename(columns={"size": "pitch_count"})
    )
    agg["fatigue_bucket"] = agg["pitch_count"].apply(classify_bucket)
    return agg


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def compute_activation_rates(apr: pd.DataFrame, sep: pd.DataFrame) -> pd.DataFrame:
    """Rows = window, cols = bucket, values = count and pct."""
    rows = []
    for label, df in [("april", apr), ("september", sep)]:
        counts = df["fatigue_bucket"].value_counts()
        total = counts.sum()
        rows.append(
            {
                "window": label,
                "low_n": counts.get("low", 0),
                "medium_n": counts.get("medium", 0),
                "high_n": counts.get("high", 0),
                "total_n": total,
                "low_pct": round(counts.get("low", 0) / total * 100, 1),
                "medium_pct": round(counts.get("medium", 0) / total * 100, 1),
                "high_pct": round(counts.get("high", 0) / total * 100, 1),
            }
        )
    return pd.DataFrame(rows)


def _pitcher_window_summary(df: pd.DataFrame) -> pd.DataFrame:
    """One row per pitcher: pct in each bucket across all appearances."""
    g = df.groupby("pitcher")["fatigue_bucket"].value_counts(normalize=True).unstack(fill_value=0)
    for bucket in ("low", "medium", "high"):
        if bucket not in g.columns:
            g[bucket] = 0.0
    return (
        g[["low", "medium", "high"]]
        .multiply(100)
        .rename(columns={"low": "pct_low", "medium": "pct_medium", "high": "pct_high"})
    )


def compute_per_pitcher_shift(
    apr: pd.DataFrame, sep: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per-pitcher shift table + aggregate summary."""
    apr_summary = _pitcher_window_summary(apr).add_suffix("_april")
    sep_summary = _pitcher_window_summary(sep).add_suffix("_september")

    merged = apr_summary.join(sep_summary, how="inner")
    merged["shift_high_abs"] = (merged["pct_high_april"] - merged["pct_high_september"]).abs()
    merged["shift_medium_abs"] = (merged["pct_medium_april"] - merged["pct_medium_september"]).abs()
    merged = merged.reset_index()

    summary = pd.DataFrame(
        [
            {
                "metric": "mean_shift_pct_high",
                "value": round(merged["shift_high_abs"].mean(), 2),
            },
            {
                "metric": "median_shift_pct_high",
                "value": round(merged["shift_high_abs"].median(), 2),
            },
            {
                "metric": "max_shift_pct_high",
                "value": round(merged["shift_high_abs"].max(), 2),
            },
            {
                "metric": "pct_pitchers_shift_gt_20pp",
                "value": round((merged["shift_high_abs"] > 20).mean() * 100, 1),
            },
            {
                "metric": "n_pitchers_in_cohort",
                "value": len(merged),
            },
        ]
    )
    return merged, summary


def compute_bucket_reassignment(apr: pd.DataFrame, sep: pd.DataFrame) -> pd.DataFrame:
    """Pitchers whose modal bucket changed between windows."""
    apr_modal = (
        apr.groupby("pitcher")["fatigue_bucket"]
        .agg(lambda x: x.value_counts().idxmax())
        .rename("modal_april")
    )
    sep_modal = (
        sep.groupby("pitcher")["fatigue_bucket"]
        .agg(lambda x: x.value_counts().idxmax())
        .rename("modal_september")
    )
    combined = pd.concat([apr_modal, sep_modal], axis=1).dropna()
    combined["reassigned"] = combined["modal_april"] != combined["modal_september"]
    combined["direction"] = combined.apply(
        lambda r: f"{r.modal_april}→{r.modal_september}" if r.reassigned else "stable",
        axis=1,
    )
    return combined.reset_index()


# ---------------------------------------------------------------------------
# Markdown table helpers
# ---------------------------------------------------------------------------


def _md_row(cells: list) -> str:
    return "| " + " | ".join(str(c) for c in cells) + " |"


def _md_sep(n: int) -> str:
    return "|" + "|".join(["---"] * n) + "|"


def print_activation_table(rates: pd.DataFrame) -> None:
    print("\n### Table 1 — Activation rate by fatigue bucket per window\n")
    headers = ["Window", "Low n (%)", "Medium n (%)", "High n (%)", "Total"]
    print(_md_row(headers))
    print(_md_sep(len(headers)))
    for _, r in rates.iterrows():
        print(
            _md_row(
                [
                    r["window"].capitalize(),
                    f"{int(r.low_n)} ({r.low_pct}%)",
                    f"{int(r.medium_n)} ({r.medium_pct}%)",
                    f"{int(r.high_n)} ({r.high_pct}%)",
                    int(r.total_n),
                ]
            )
        )


def print_shift_summary_table(summary: pd.DataFrame) -> None:
    print("\n### Table 2 — Per-pitcher pct_high shift (April vs September)\n")
    print(_md_row(["Metric", "Value"]))
    print(_md_sep(2))
    for _, r in summary.iterrows():
        print(_md_row([r["metric"], r["value"]]))


def print_reassignment_table(reassign: pd.DataFrame) -> None:
    total = len(reassign)
    n_reassigned = reassign["reassigned"].sum()
    pct = round(n_reassigned / total * 100, 1)
    directions = reassign[reassign["reassigned"]]["direction"].value_counts()

    print("\n### Table 3 — Bucket reassignment rate\n")
    print(_md_row(["Metric", "Value"]))
    print(_md_sep(2))
    print(_md_row(["Total pitchers in cohort", total]))
    print(_md_row(["Pitchers reassigned", f"{n_reassigned} ({pct}%)"]))
    print(_md_row(["Pitchers stable", f"{total - n_reassigned} ({round(100 - pct, 1)}%)"]))
    print()
    print(_md_row(["Direction", "Count"]))
    print(_md_sep(2))
    for direction, count in directions.items():
        print(_md_row([direction, count]))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Compute stationarity metrics for mini-probe.")
    p.add_argument("--data-dir", default="data/raw", type=Path)
    p.add_argument("--output-dir", default="data/processed/mini_probe", type=Path)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # --- load ---
    april_raw = pd.read_parquet(args.data_dir / "statcast_2024_april.parquet")
    sep_raw = pd.read_parquet(args.data_dir / "statcast_2024_september.parquet")

    # --- per-game aggregation ---
    april_pg = build_per_game_df(april_raw)
    sep_pg = build_per_game_df(sep_raw)

    april_pg.to_csv(args.output_dir / "window_april_per_game.csv", index=False)
    sep_pg.to_csv(args.output_dir / "window_september_per_game.csv", index=False)

    # --- comparable cohort ---
    cohort = set(april_pg["pitcher"].unique()) & set(sep_pg["pitcher"].unique())
    print(f"\nComparable cohort: {len(cohort)} pitchers in both windows.", file=sys.stderr)

    apr_cohort = april_pg[april_pg["pitcher"].isin(cohort)].copy()
    sep_cohort = sep_pg[sep_pg["pitcher"].isin(cohort)].copy()

    # --- metric 1: activation rates ---
    rates = compute_activation_rates(apr_cohort, sep_cohort)
    rates.to_csv(args.output_dir / "activation_rates.csv", index=False)

    # --- metric 2: per-pitcher shift ---
    per_pitcher, shift_summary = compute_per_pitcher_shift(apr_cohort, sep_cohort)
    per_pitcher.to_csv(args.output_dir / "per_pitcher_shift.csv", index=False)
    shift_summary.to_csv(args.output_dir / "shift_summary.csv", index=False)

    # --- metric 3: bucket reassignment ---
    reassign = compute_bucket_reassignment(apr_cohort, sep_cohort)
    reassign.to_csv(args.output_dir / "bucket_reassignment.csv", index=False)

    # --- print tables ---
    print_activation_table(rates)
    print_shift_summary_table(shift_summary)
    print_reassignment_table(reassign)

    print(f"\nOutputs written to {args.output_dir}/", file=sys.stderr)


if __name__ == "__main__":
    main()
