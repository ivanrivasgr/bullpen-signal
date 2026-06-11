"""silver_matchup_signals — materialized matchup signals per pitch event.

dbt Python model. Reads silver_matchup_events and emits MatchupSignal
rows. The signal-generation logic lives in signals/matchup_signal.py;
this model is the only consumer that materializes it.

Emission model (ADR 0020, completing the revision loop):

- A confirmed pitch emits ONE signal. lineup_state was never in doubt,
  so there is a single matchup keyed on the real handedness, with
  confidence_band = full.

- An uncertain pitch emits TWO signals for the same pitch:
    1. A reduced-confidence signal computed from the PROJECTED batter's
       handedness (projected_handedness_matchup). This is what the
       system actually knew during the uncertainty window — it had not
       yet seen the real lineup, so the signal must reflect the
       projection, not the truth. lineup_state_at_emission = uncertain.
    2. A full-confidence signal computed from the REAL batter's
       handedness (handedness_matchup). This is the resolution: once the
       lineup confirmed, the system recomputes against the truth.
       lineup_state_at_emission = confirmed.

  The downstream revision producer groups by natural key and compares
  the two emissions per pitch. If the projected and real handedness
  agree, the signal_value is identical and the revision is
  baseline_confirmed. If they differ, signal_value differs and the
  revision is material_update.

An uncertain pitch with no projection (projected_batter_id null —
team_id missing, or projection failed across all ADR 0015 layers)
cannot produce a meaningful reduced signal. It emits a single signal
exactly like a confirmed pitch, because the system had nothing to act
on during the window; there is no projection to later confirm or
overturn.

Because a pitch can now legitimately produce two rows, the natural key
for uniqueness widens to (game_pk, at_bat_number, pitch_number,
lineup_state_at_emission). This is enforced by a custom test, not by
the incremental unique_key, since dbt's unique_key would treat the two
emissions as a conflict and keep only one.
"""

from __future__ import annotations

import sys
from pathlib import Path


def model(dbt, session):
    dbt.config(
        materialized="incremental",
        unique_key=["game_pk", "at_bat_number", "pitch_number", "lineup_state_at_emission"],
    )

    repo_root = Path.cwd().resolve().parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    import pandas as pd

    from signals.matchup_signal import generate_matchup_signal

    matchup_events = dbt.ref("silver_matchup_events").df()

    output_rows = []
    for _, row in matchup_events.iterrows():
        row_dict = row.to_dict()
        is_uncertain = row_dict.get("lineup_state") == "uncertain"
        has_projection = row_dict.get("projected_batter_id") is not None

        if is_uncertain and has_projection:
            # Emission 1: reduced signal from the PROJECTED handedness.
            # Override the matchup the signal generator sees so it computes
            # against what the system knew during the window, and force the
            # lineup_state to uncertain so the confidence band is reduced.
            reduced_input = dict(row_dict)
            reduced_input["handedness_matchup"] = row_dict.get("projected_handedness_matchup")
            reduced_input["lineup_state"] = "uncertain"
            reduced_signal = generate_matchup_signal(reduced_input)
            reduced_row = dict(row_dict)
            reduced_row["signal_value"] = reduced_signal.signal_value
            reduced_row["confidence_band"] = reduced_signal.confidence_band
            reduced_row["lineup_state_at_emission"] = "uncertain"
            output_rows.append(reduced_row)

            # Emission 2: full signal from the REAL handedness (resolution).
            full_input = dict(row_dict)
            full_input["lineup_state"] = "confirmed"
            full_signal = generate_matchup_signal(full_input)
            full_row = dict(row_dict)
            full_row["signal_value"] = full_signal.signal_value
            full_row["confidence_band"] = full_signal.confidence_band
            full_row["lineup_state_at_emission"] = "confirmed"
            output_rows.append(full_row)
        else:
            # Single emission: confirmed pitch, or uncertain-without-projection.
            # The signal generator uses the row's own lineup_state to pick the
            # confidence band, so uncertain-without-projection still records a
            # reduced band, honestly reflecting that the system was uncertain
            # but had no projection to act on.
            signal = generate_matchup_signal(row_dict)
            single_row = dict(row_dict)
            single_row["signal_value"] = signal.signal_value
            single_row["confidence_band"] = signal.confidence_band
            single_row["lineup_state_at_emission"] = signal.lineup_state_at_emission
            output_rows.append(single_row)

    return pd.DataFrame(output_rows)
