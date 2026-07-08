"""Anti-drift contract: the generated runtime map equals the seed CSV.

signals/matchup_calibration.py and dbt/seeds/matchup_calibration.csv are
two outputs of the same generator run (ADR 0027). If either were edited
or regenerated alone, the runtime signal and the audit trail would
diverge silently. This test pins them together: every measured bucket in
the seed must appear in the runtime map with the same value, the
mirrored switch-pitcher entries must equal their documented sources, and
the map must cover exactly the nine buckets plus the None fallback.
"""

from __future__ import annotations

import csv
from pathlib import Path

from signals.matchup_calibration import CALIBRATED_SIGNAL_VALUES

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SEED_PATH = _REPO_ROOT / "dbt" / "seeds" / "matchup_calibration.csv"


def _seed_values() -> dict[str, float]:
    with _SEED_PATH.open(newline="") as f:
        return {row["matchup"]: float(row["signal_value"]) for row in csv.DictReader(f)}


class TestRuntimeMapMatchesSeed:
    def test_seed_exists(self) -> None:
        assert _SEED_PATH.exists()

    def test_measured_buckets_match_seed(self) -> None:
        seed = _seed_values()
        assert len(seed) == 6
        for matchup, value in seed.items():
            assert CALIBRATED_SIGNAL_VALUES[matchup] == value

    def test_mirrored_entries_match_their_sources(self) -> None:
        assert CALIBRATED_SIGNAL_VALUES["S_vs_R"] == CALIBRATED_SIGNAL_VALUES["R_vs_R"]
        assert CALIBRATED_SIGNAL_VALUES["S_vs_L"] == CALIBRATED_SIGNAL_VALUES["L_vs_L"]
        assert CALIBRATED_SIGNAL_VALUES["S_vs_S"] == 0.0

    def test_map_covers_exactly_the_nine_buckets(self) -> None:
        """Exactly the nine handedness buckets -- no None key. An irresolvable
        matchup is handled by compute_signal_fields returning None (ADR 0028),
        not by a None entry in the calibrated map."""
        expected = {
            "R_vs_R",
            "R_vs_L",
            "R_vs_S",
            "L_vs_R",
            "L_vs_L",
            "L_vs_S",
            "S_vs_R",
            "S_vs_L",
            "S_vs_S",
        }
        assert set(CALIBRATED_SIGNAL_VALUES.keys()) == expected
