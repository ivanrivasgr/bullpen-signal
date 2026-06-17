"""PyFlink UDF deriving handedness_matchup from a pitch's player IDs.

The batch path derives handedness_matchup in silver_matchup_events by
LEFT JOINing the player_handedness seed three times (pitcher, batter,
projected batter) and concatenating. The streaming path cannot join an
external seed mid-stream as cleanly, but the seed is small and static,
so this resolves it in a UDF instead: the seed is loaded once into an
in-memory map (signals.handedness_lookup) and the matchup is derived
with the shared core function (signals.matchup_core.derive_handedness_matchup).

Two derivations matter, mirroring the batch model:
- the real matchup, from pitcher_id and batter_id
- the projected matchup, from pitcher_id and projected_batter_id, used
  for the reduced-confidence signal during the uncertainty window (ADR 0020)

Both call the same shared derivation as dbt, so the streaming and batch
handedness matchups cannot drift. Like the signal UDF, the logic lives
in a plain function (compute_handedness_fields) that needs no Flink, so
the contract test can assert equivalence without a cluster. The Flink
Row wrapping happens only in the lazily-built UDF.
"""

from __future__ import annotations

from signals.handedness_lookup import lookup_hand
from signals.matchup_core import derive_handedness_matchup


def compute_handedness_fields(
    pitcher_id: int | None,
    batter_id: int | None,
    projected_batter_id: int | None,
) -> tuple[str | None, str | None]:
    """Resolve (handedness_matchup, projected_handedness_matchup) for a pitch.

    Mirrors silver_matchup_events: the real matchup from pitcher vs batter,
    and the projected matchup from pitcher vs projected batter (None when
    there was no projection). A player absent from the seed yields None on
    its side, which propagates to a None matchup — the same graceful
    degradation as the dbt LEFT JOIN.
    """
    pitcher_hand = lookup_hand(pitcher_id, "pitcher")
    batter_hand = lookup_hand(batter_id, "batter")
    projected_batter_hand = lookup_hand(projected_batter_id, "batter")

    handedness_matchup = derive_handedness_matchup(pitcher_hand, batter_hand)
    projected_handedness_matchup = derive_handedness_matchup(pitcher_hand, projected_batter_hand)
    return (handedness_matchup, projected_handedness_matchup)


def build_handedness_udf():
    """Build the Flink UDF lazily so importing this module needs no PyFlink.

    Returns a ROW of (handedness_matchup, projected_handedness_matchup),
    both nullable strings. The natural-key columns travel alongside the
    UDF in the job's SELECT, not through it.
    """
    from pyflink.common import Row
    from pyflink.table import DataTypes
    from pyflink.table.udf import udf

    @udf(
        result_type=DataTypes.ROW(
            [
                DataTypes.FIELD("handedness_matchup", DataTypes.STRING()),
                DataTypes.FIELD("projected_handedness_matchup", DataTypes.STRING()),
            ]
        )
    )
    def handedness_udf(pitcher_id, batter_id, projected_batter_id):
        handedness_matchup, projected_handedness_matchup = compute_handedness_fields(
            pitcher_id, batter_id, projected_batter_id
        )
        return Row(handedness_matchup, projected_handedness_matchup)

    return handedness_udf
