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

    from signals.matchup_core import compute_signal_fields, plan_signal_emissions

    matchup_events = dbt.ref("silver_matchup_events").df()

    output_rows = []
    for _, row in matchup_events.iterrows():
        row_dict = row.to_dict()
        has_projection = row_dict.get("projected_batter_id") is not None

        # plan_signal_emissions decides the expansion (one or two emissions,
        # and which handedness matchup + lineup_state each uses), shared with
        # the streaming path so the two cannot drift. compute_signal_fields
        # then computes each emission's signal. Both live in matchup_core.
        emissions = plan_signal_emissions(
            lineup_state=row_dict.get("lineup_state"),
            handedness_matchup=row_dict.get("handedness_matchup"),
            projected_handedness_matchup=row_dict.get("projected_handedness_matchup"),
            has_projection=has_projection,
        )

        for matchup, emission_state in emissions:
            signal_value, confidence_band, lineup_state_at_emission = compute_signal_fields(
                matchup, emission_state
            )
            # The signal is computed from the per-emission matchup (projected
            # for the reduced emission, real for the full one). The output
            # row's handedness_matchup column is left as the row's real
            # matchup, exactly as before — the reconciliation marts group by
            # it, so this refactor must not change that value. Changing the
            # reduced row's attribution is a product decision for its own ADR.
            out = dict(row_dict)
            out["signal_value"] = signal_value
            out["confidence_band"] = confidence_band
            out["lineup_state_at_emission"] = lineup_state_at_emission
            output_rows.append(out)

    return pd.DataFrame(output_rows)
