"""PyFlink table function expanding a pitch into its signal emissions.

The batch path expands each pitch into one or two signal rows in the
silver_matchup_signals dbt model, by calling plan_signal_emissions then
compute_signal_fields. The streaming job needs the same expansion: a
confirmed pitch yields one signal row, an uncertain pitch with a
projection yields two (reduced from the projected handedness, full from
the real one). A scalar UDF cannot do this — one input row must produce a
variable number of output rows — so this is a table function (UDTF).

Both core calls are the shared, already-tested functions in
signals.matchup_core, so the streaming expansion cannot drift from the
batch expansion (ADR 0021). compute_emission_rows is a plain generator
that needs no Flink, so the contract test exercises it directly; the
UDTF wrapper only adds the Flink Row typing and yields.
"""

from __future__ import annotations

from collections.abc import Iterator

from signals.matchup_core import compute_signal_fields, plan_signal_emissions


def compute_emission_rows(
    lineup_state: str,
    handedness_matchup: str | None,
    projected_handedness_matchup: str | None,
    has_projection: bool,
) -> Iterator[tuple[float, str, str]]:
    """Yield one (signal_value, confidence_band, lineup_state_at_emission)
    tuple per emission this pitch produces.

    plan_signal_emissions decides the expansion — one or two emissions,
    and which handedness matchup + lineup_state each uses — and
    compute_signal_fields computes each. Identical to the batch loop in
    silver_matchup_signals, by construction: same two shared functions.
    """
    emissions = plan_signal_emissions(
        lineup_state=lineup_state,
        handedness_matchup=handedness_matchup,
        projected_handedness_matchup=projected_handedness_matchup,
        has_projection=has_projection,
    )
    for matchup, emission_state in emissions:
        yield compute_signal_fields(matchup, emission_state)


def build_emission_udtf():
    """Build the Flink table function lazily so importing this module needs
    no PyFlink (the contract test runs without a cluster).

    Emits a row of (signal_value, confidence_band, lineup_state_at_emission)
    for each emission. One input pitch produces one or two output rows.
    """
    from pyflink.common import Row
    from pyflink.table import DataTypes
    from pyflink.table.udf import udtf

    @udtf(
        result_types=DataTypes.ROW(
            [
                DataTypes.FIELD("signal_value", DataTypes.FLOAT()),
                DataTypes.FIELD("confidence_band", DataTypes.STRING()),
                DataTypes.FIELD("lineup_state_at_emission", DataTypes.STRING()),
            ]
        )
    )
    def emission_udtf(
        lineup_state, handedness_matchup, projected_handedness_matchup, has_projection
    ):
        for signal_value, confidence_band, lineup_state_at_emission in compute_emission_rows(
            lineup_state,
            handedness_matchup,
            projected_handedness_matchup,
            has_projection,
        ):
            yield Row(signal_value, confidence_band, lineup_state_at_emission)

    return emission_udtf
