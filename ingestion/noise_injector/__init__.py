"""Inject realistic noise into the replay stream.

The whole point of Bullpen Signal is to show what each architecture does under
realistic conditions. A clean stream is a useless benchmark. This module
produces three kinds of noise:

1. Late arrivals: a pitch whose event_time is earlier than the stream clock.
   Exercises Flink's event-time watermarks and late-data handling.
2. Duplicates: the same pitch published twice. Exercises idempotency.
3. Corrections: a CorrectionEvent emitted hours or innings after the original,
   mimicking MLB official scoring changes or Statcast pitch-type revisions.

Rates are configurable via the ReplayConfig. Defaults are conservative.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from datetime import timedelta

from ingestion.replay_engine.events import CorrectionEvent, PitchEvent


def maybe_inject_noise(
    event: PitchEvent,
    *,
    late_arrival_prob: float,
    duplicate_prob: float,
    correction_prob: float,
    rng: random.Random,
) -> Iterator[PitchEvent | CorrectionEvent]:
    """Yield the original event plus any injected noise derived from it.

    Order matters: the original event is always yielded first. Duplicates are
    yielded immediately after. Late arrivals are yielded by bumping the event's
    ingest_time backwards relative to the stream clock (the caller handles the
    publish delay separately). Corrections are emitted as a distinct event
    targeting the original.
    """
    yield event

    if rng.random() < duplicate_prob:
        dup = event.model_copy(update={"is_duplicate": True})
        yield dup

    if rng.random() < late_arrival_prob:
        late = event.model_copy(
            update={
                "event_time": event.event_time - timedelta(seconds=rng.randint(30, 300)),
                "is_late_arrival": True,
            }
        )
        yield late

    if rng.random() < correction_prob and event.pitch_type is not None:
        corrected_type = _flip_pitch_type(event.pitch_type, rng)
        if corrected_type != event.pitch_type:
            correction = CorrectionEvent(
                event_time=event.event_time + timedelta(minutes=rng.randint(5, 45)),
                ingest_time=event.ingest_time + timedelta(minutes=rng.randint(5, 45)),
                game_pk=event.game_pk,
                original_pitch_uid=_pitch_uid(event),
                field="pitch_type",
                old_value=event.pitch_type,
                new_value=corrected_type,
            )
            yield correction


def _pitch_uid(event: PitchEvent) -> str:
    return f"{event.game_pk}:{event.at_bat_number}:{event.pitch_number}"


_COMMON_CONFUSIONS: dict[str, list[str]] = {
    "FF": ["FT", "SI"],
    "FT": ["FF", "SI"],
    "SI": ["FT", "FF"],
    "SL": ["CU", "FC"],
    "CU": ["SL", "KC"],
    "KC": ["CU"],
    "CH": ["FS"],
    "FS": ["CH"],
}


def _flip_pitch_type(pitch_type: str, rng: random.Random) -> str:
    candidates = _COMMON_CONFUSIONS.get(pitch_type, [])
    if not candidates:
        return pitch_type
    return rng.choice(candidates)
