"""Detect and emit matchup signal revisions.

Implements the runtime side of ADR 0017. The function `detect_revision`
takes two matchup signal emissions for the same natural key (the new
one and the one it might supersede) and returns either a
MatchupRevisionEvent describing the transition, or None if there is
no revision worth emitting.

This module is intentionally pure: no I/O, no logging, no state. The
revision producer (a Flink job or batch process) owns the work of
collecting consecutive signals per natural key and deciding when to
call this function. ADR 0017 explicitly leaves topology to Milestone 3.

Three revision categories from ADR 0017:

- material_update: signal_value changed between previous and new.
  Triggered by lineup confirmation revealing a different actual batter,
  or by a correction event changing matchup-relevant features.

- baseline_confirmed: signal_value is identical but confidence_band
  rose (typically reduced -> full when lineup confirmed and the
  projected batter was correct). Phase 3 uses these to calibrate
  projection accuracy.

- suppressed_by_governance: emitted only by the Phase 3 reconciliation
  layer, not by this function. detect_revision does not produce this
  category because deciding "this suppressed signal would have been
  correct" requires comparing against canonical outcomes that live
  outside the signal stream. The reconciliation batch produces them
  directly when it joins suppressed signals against the outcomes mart.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from ingestion.replay_engine.events import MatchupRevisionEvent
from signals.matchup_signal import MatchupSignal

# Ordering for confidence_band so we can tell whether confidence rose.
# 'suppressed' has the least signal, 'full' has the most. A revision
# moving from a lower band to a higher one is a confidence rise.
_CONFIDENCE_RANK: dict[Literal["full", "reduced", "suppressed"], int] = {
    "suppressed": 0,
    "reduced": 1,
    "full": 2,
}


def detect_revision(
    previous_signal: MatchupSignal,
    new_signal: MatchupSignal,
    source_event_id: str,
    revision_event_time: datetime | None = None,
) -> MatchupRevisionEvent | None:
    """Return a MatchupRevisionEvent if the transition warrants one, else None.

    The two signals must share the same natural key (game_pk,
    at_bat_number, pitch_number). A mismatch is a programmer error.

    `source_event_id` identifies the upstream event that triggered the
    re-evaluation. The caller knows this (it just consumed the event);
    detect_revision does not. Per ADR 0017, this is the recoverable
    cause pointer.

    `revision_event_time` is optional; defaults to now(UTC) at the moment
    of the call. Tests can pass an explicit time for determinism.

    Returns None for no-op transitions (identical signal_value AND
    identical confidence_band). Phase 3's reconciliation layer is the
    sole producer of suppressed_by_governance revisions; this function
    never emits them.
    """
    _assert_same_natural_key(previous_signal, new_signal)

    signal_value_changed = previous_signal.signal_value != new_signal.signal_value
    confidence_rose = (
        _CONFIDENCE_RANK[new_signal.confidence_band]
        > _CONFIDENCE_RANK[previous_signal.confidence_band]
    )

    if not signal_value_changed and not confidence_rose:
        # Identical emission, or confidence dropped/stayed flat with no
        # value change. Nothing worth revising.
        return None

    # When signal_value changed -> material_update. Otherwise the
    # confidence rose (we already returned None for the no-op case
    # above) and the revision is baseline_confirmed.
    revision_type: Literal["material_update", "baseline_confirmed"] = (
        "material_update" if signal_value_changed else "baseline_confirmed"
    )

    event_time = revision_event_time if revision_event_time is not None else datetime.now(UTC)

    return MatchupRevisionEvent(
        event_time=event_time,
        ingest_time=event_time,
        game_pk=new_signal.game_pk,
        at_bat_number=new_signal.at_bat_number,
        pitch_number=new_signal.pitch_number,
        pitcher_id=new_signal.pitcher_id,
        batter_id=new_signal.batter_id,
        revision_type=revision_type,
        previous_signal_value=previous_signal.signal_value,
        current_signal_value=new_signal.signal_value,
        previous_confidence_band=previous_signal.confidence_band,
        current_confidence_band=new_signal.confidence_band,
        source_event_id=source_event_id,
    )


def _assert_same_natural_key(a: MatchupSignal, b: MatchupSignal) -> None:
    """Raise ValueError if two signals do not share the same pitch identity."""
    a_key = (a.game_pk, a.at_bat_number, a.pitch_number)
    b_key = (b.game_pk, b.at_bat_number, b.pitch_number)
    if a_key != b_key:
        raise ValueError(
            f"detect_revision called with mismatched natural keys: "
            f"previous={a_key}, new={b_key}. Caller must group signals "
            f"by (game_pk, at_bat_number, pitch_number) before calling."
        )
