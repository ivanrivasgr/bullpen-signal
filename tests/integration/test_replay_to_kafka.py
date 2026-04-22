"""Integration tests that require the local stack.

Run with: `pytest -m integration`.
Skip by default so CI and the fast feedback loop stay clean.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(reason="Requires local stack; Phase 1 wiring.")
def test_replay_publishes_to_kafka_end_to_end() -> None:
    """Run the replay engine at dry-run=False and confirm pitches land on pitches.raw."""
    pass
