"""PyFlink UDF wrapping the shared matchup signal definition.

ADR 0021 requires the streaming and batch paths to use the same signal
definition, not two implementations that can drift. The batch path calls
signals.matchup_signal.generate_matchup_signal directly (in the dbt
Python model). The streaming path cannot call it the same way — a Flink
Table API job runs the function inside a Python UDF, and a UDF must
return Flink-serializable types, not a Pydantic model.

This module bridges the two. compute_matchup_fields is a plain function
that calls the shared pure definition and unpacks the result into the
three scalar fields reconciliation compares (signal_value,
confidence_band, lineup_state_at_emission). matchup_signal_udf is the
same logic wrapped as a Flink ROW-returning UDF.

Keeping the logic in compute_matchup_fields — a plain function, no Flink
types in its body — means the equivalence between this path and the
batch path is testable without a Flink cluster. The contract test in
tests/unit/streaming asserts that for every handedness matchup and
lineup_state, this path and generate_matchup_signal agree. If the shared
definition changes and this wrapper is not updated, the test fails. That
is the anti-drift guarantee ADR 0001 and ADR 0021 call for.
"""

from __future__ import annotations

from signals.matchup_core import compute_signal_fields


def compute_matchup_fields(
    handedness_matchup: str | None,
    lineup_state: str,
) -> tuple[float, str, str]:
    """Compute the three signal fields via the shared pydantic-free core.

    Returns (signal_value, confidence_band, lineup_state_at_emission) —
    the exact triple the reconciliation layer compares between the
    streaming and batch paths, so the streaming emission stays apples to
    apples with the batch silver_matchup_signals rows.

    Only handedness_matchup and lineup_state determine the signal. The
    natural-key fields that identify the pitch are carried by the Flink
    job around the UDF, not computed here.

    Raises ValueError on an unknown lineup_state, same as the batch path.
    """
    # Call the pydantic-free core directly. The natural-key fields
    # (event_time, game_pk, ...) are not needed to compute the signal
    # values — they identify the pitch and are carried by the Flink job
    # around the UDF, not through it. The UDF returns only the three
    # computed fields. This keeps Pydantic out of the Flink runtime.
    return compute_signal_fields(
        handedness_matchup=handedness_matchup,
        lineup_state=lineup_state,
    )


def build_matchup_signal_udf():
    """Build the Flink UDF lazily so importing this module does not require
    a running PyFlink environment (e.g. for the contract test).

    The UDF wraps compute_matchup_fields and declares a ROW return type
    matching the three reconciliation fields. Called by the Flink job at
    job-construction time.
    """
    from pyflink.common import Row
    from pyflink.table import DataTypes
    from pyflink.table.udf import udf

    @udf(
        result_type=DataTypes.ROW(
            [
                DataTypes.FIELD("signal_value", DataTypes.FLOAT()),
                DataTypes.FIELD("confidence_band", DataTypes.STRING()),
                DataTypes.FIELD("lineup_state_at_emission", DataTypes.STRING()),
            ]
        )
    )
    def matchup_signal_udf(handedness_matchup, lineup_state):
        # compute_matchup_fields returns a plain tuple (kept pure and
        # Flink-free so the contract test needs no Flink). The UDF's
        # declared ROW result_type requires a pyflink Row, not a tuple,
        # so wrap it here — the one place that knows the Flink runtime.
        signal_value, confidence_band, lineup_state_at_emission = compute_matchup_fields(
            handedness_matchup, lineup_state
        )
        return Row(signal_value, confidence_band, lineup_state_at_emission)

    return matchup_signal_udf
