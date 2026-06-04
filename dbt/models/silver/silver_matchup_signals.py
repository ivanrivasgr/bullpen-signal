"""silver_matchup_signals — materialized matchup signals per pitch event.

dbt Python model. Reads silver_matchup_events as a DataFrame, applies
the pure signal-generation function from signals.matchup_signal to each
row, and returns the DataFrame with three additional columns:
signal_value, confidence_band, lineup_state_at_emission.

This is the materialization side of ADR 0016. The signal-generation
logic lives in one place (signals/matchup_signal.py); this model is
the only consumer that materializes it to the warehouse. Phase 3 reads
this table as the canonical record of "what the system would have
emitted" for reconciliation against actual outcomes.

The model imports the project's signals package by adding the repo root
to sys.path inside model(). dbt-duckdb runs Python models in a process
with the dbt project as cwd, so the repo root is two levels up.
"""

from __future__ import annotations

import sys
from pathlib import Path


def model(dbt, session):
    dbt.config(
        materialized="incremental",
        unique_key=["game_pk", "at_bat_number", "pitch_number"],
    )

    # dbt compiles Python models to /tmp/ before executing them, so
    # Path(__file__) does NOT point at the model source. dbt-duckdb runs
    # with cwd set to the dbt project directory (dbt/), so the repo root
    # is one parent up from cwd. We add it to sys.path so we can import
    # the project's signals package.
    repo_root = Path.cwd().resolve().parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from signals.matchup_signal import generate_matchup_signal

    # Pull the upstream model as a pandas DataFrame.
    matchup_events = dbt.ref("silver_matchup_events").df()

    # Apply the signal generator row by row. The function returns a
    # MatchupSignal Pydantic model; we extract the three new fields and
    # leave the rest of the row intact for downstream joinability.
    def _enrich(row):
        signal = generate_matchup_signal(row.to_dict())
        return (
            signal.signal_value,
            signal.confidence_band,
            signal.lineup_state_at_emission,
        )

    enriched = matchup_events.apply(_enrich, axis=1, result_type="expand")
    enriched.columns = ["signal_value", "confidence_band", "lineup_state_at_emission"]

    matchup_events["signal_value"] = enriched["signal_value"]
    matchup_events["confidence_band"] = enriched["confidence_band"]
    matchup_events["lineup_state_at_emission"] = enriched["lineup_state_at_emission"]

    return matchup_events
