"""CLI-level tests for ingestion.replay_engine.run.

These tests verify that CLI flags route to the right downstream
config objects. They are not full replay-loop tests — the replay
itself is exercised elsewhere.

The harness feeds main() an empty Statcast DataFrame, so main()
constructs its config objects and then exits with code 1 at the
"no data for date" guard. That guard runs AFTER UncertaintyConfig
is built, which is exactly what these tests need: the config is
captured by the spy before the early exit. The exit itself is the
correct production behavior for an empty replay and is not the
subject under test, so the assertions target the captured config
rather than the exit code.
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
from click.testing import CliRunner

from ingestion.replay_engine.run import main
from ingestion.replay_engine.uncertainty_window import UncertaintyConfig


class TestUncertaintyRateFlag:
    """The --uncertainty-rate CLI flag must reach UncertaintyConfig.late_game_rate."""

    def _capture_config(self, *extra_args: str) -> UncertaintyConfig:
        """Invoke main() and return the single UncertaintyConfig it builds.

        main() exits at the empty-DataFrame guard, but UncertaintyConfig
        is constructed before that guard, so the spy captures it. Asserts
        exactly one config was built and returns it.
        """
        configs_seen: list[UncertaintyConfig] = []
        original = UncertaintyConfig

        def spy(*args: object, **kwargs: object) -> UncertaintyConfig:
            cfg = original(*args, **kwargs)
            configs_seen.append(cfg)
            return cfg

        with (
            patch("ingestion.replay_engine.run.UncertaintyConfig", side_effect=spy),
            patch("ingestion.replay_engine.run.load_statcast_date") as load_mock,
        ):
            load_mock.return_value = pd.DataFrame()  # empty -> exits at guard
            runner = CliRunner()
            runner.invoke(
                main,
                ["--game-date", "2024-04-15", "--dry-run", *extra_args],
            )

        assert len(configs_seen) == 1, (
            f"Expected exactly one UncertaintyConfig, got {len(configs_seen)}"
        )
        return configs_seen[0]

    def test_default_uses_adr_0014_rate(self) -> None:
        config = self._capture_config()
        assert config.late_game_rate == 0.15  # ADR 0014 default

    def test_explicit_one_forces_every_game(self) -> None:
        config = self._capture_config("--uncertainty-rate", "1.0")
        assert config.late_game_rate == 1.0

    def test_explicit_zero_disables(self) -> None:
        config = self._capture_config("--uncertainty-rate", "0.0")
        assert config.late_game_rate == 0.0

    def test_seed_propagates_to_base_seed(self) -> None:
        config = self._capture_config("--seed", "999")
        assert config.base_seed == 999


class TestUncertaintyRateValidation:
    """Click rejects out-of-range rates before main() runs."""

    def _invoke(self, *extra_args: str) -> int:
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--game-date", "2024-04-15", "--dry-run", *extra_args],
        )
        return result.exit_code

    def test_rate_above_one_rejected(self) -> None:
        # Click exits with code 2 on parameter validation errors.
        assert self._invoke("--uncertainty-rate", "1.5") == 2

    def test_negative_rate_rejected(self) -> None:
        assert self._invoke("--uncertainty-rate", "-0.1") == 2
