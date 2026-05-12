"""Unit tests for scripts/mini_probe/compute_stationarity.py."""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[3] / "scripts" / "mini_probe"))
from compute_stationarity import (
    build_per_game_df,
    classify_bucket,
    compute_activation_rates,
)

# ---------------------------------------------------------------------------
# Boundary values — must match SQL CASE logic exactly (ADR-0008)
# ---------------------------------------------------------------------------


def test_fatigue_bucket_edge_cases():
    """Boundary values must match the SQL CASE logic exactly."""
    assert classify_bucket(0) == "low"  # zero pitches
    assert classify_bucket(24) == "low"  # just under threshold
    assert classify_bucket(25) == "medium"  # exactly at low/medium boundary
    assert classify_bucket(49) == "medium"  # just under threshold
    assert classify_bucket(50) == "high"  # exactly at medium/high boundary
    assert classify_bucket(150) == "high"  # well above


# ---------------------------------------------------------------------------
# Per-game counts — synthetic fixture
# ---------------------------------------------------------------------------


def _make_fixture(n_pitchers: int = 10, n_games: int = 3, pitches_per: int = 30) -> pd.DataFrame:
    """Synthetic raw dataframe: each (pitcher, game) has pitches_per pitches."""
    rows = []
    for p in range(n_pitchers):
        for g in range(n_games):
            for _ in range(pitches_per):
                rows.append({"pitcher": p, "game_pk": g})
    return pd.DataFrame(rows)


def test_per_game_pitcher_count_correct():
    """10 pitchers x 3 games x 30 pitches -> 30 rows each, all 'medium' bucket."""
    raw = _make_fixture(n_pitchers=10, n_games=3, pitches_per=30)
    result = build_per_game_df(raw)

    assert len(result) == 30  # 10 pitchers x 3 games
    assert (result["pitch_count"] == 30).all()
    assert (result["fatigue_bucket"] == "medium").all()


def test_per_game_pitcher_count_low_bucket():
    """10 pitchers x 3 games x 10 pitches -> all 'low' bucket."""
    raw = _make_fixture(n_pitchers=10, n_games=3, pitches_per=10)
    result = build_per_game_df(raw)
    assert (result["fatigue_bucket"] == "low").all()


def test_per_game_pitcher_count_high_bucket():
    """10 pitchers x 3 games x 60 pitches -> all 'high' bucket."""
    raw = _make_fixture(n_pitchers=10, n_games=3, pitches_per=60)
    result = build_per_game_df(raw)
    assert (result["fatigue_bucket"] == "high").all()


# ---------------------------------------------------------------------------
# Cohort intersection
# ---------------------------------------------------------------------------


def _make_per_game(pitcher_ids: list[int], game_pk: int = 0) -> pd.DataFrame:
    """Minimal per-game DataFrame for a set of pitchers."""
    return pd.DataFrame(
        {
            "pitcher": pitcher_ids,
            "game_pk": [game_pk] * len(pitcher_ids),
            "pitch_count": [30] * len(pitcher_ids),
            "fatigue_bucket": ["medium"] * len(pitcher_ids),
        }
    )


def test_cohort_intersection_is_correct():
    """Intersection of 7-pitcher window A and 5-pitcher window B = 3 shared."""
    window_a = _make_per_game([1, 2, 3, 4, 5, 6, 7])
    window_b = _make_per_game([3, 4, 5, 8, 9])
    cohort = set(window_a["pitcher"].unique()) & set(window_b["pitcher"].unique())
    assert cohort == {3, 4, 5}
    assert len(cohort) == 3


# ---------------------------------------------------------------------------
# Activation rate rows sum to 100%
# ---------------------------------------------------------------------------


def _make_mixed_per_game(pitcher_base: int = 0) -> pd.DataFrame:
    """Returns a per-game df with bucket counts that produce clean percentages.

    5 low + 3 medium + 2 high = 10 rows → 50% + 30% + 20% = 100.0% exactly.
    """
    return pd.DataFrame(
        {
            "pitcher": list(range(pitcher_base, pitcher_base + 10)),
            "game_pk": [0] * 10,
            "pitch_count": [10] * 5 + [30] * 3 + [60] * 2,
            "fatigue_bucket": ["low"] * 5 + ["medium"] * 3 + ["high"] * 2,
        }
    )


def test_activation_rate_sums_to_100_per_window():
    """pct columns must sum to 100.0 for each window row."""
    apr = _make_mixed_per_game(pitcher_base=0)
    sep = _make_mixed_per_game(pitcher_base=20)
    rates = compute_activation_rates(apr, sep)

    for _, row in rates.iterrows():
        total_pct = round(row["low_pct"] + row["medium_pct"] + row["high_pct"], 1)
        assert total_pct == 100.0, f"Window {row['window']}: pcts sum to {total_pct}"
