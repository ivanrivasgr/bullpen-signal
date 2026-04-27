"""Derive GameStateEvent emissions from the Statcast pitch stream.

Statcast carries enough context to infer most game-state transitions: inning
boundaries, pitching changes (when pitcher_id changes between consecutive
pitches in the same game), scoring plays (when home_score or away_score
increments), and game start/end.

What Statcast cannot carry on its own: pinch-hit events (require the manager's
intent + batter lookup) and lineup confirmations (require StatsAPI's lineup
feed). Those belong in Phase 2 alongside the lineup-latency work (ADR 0009).

This module is intentionally a pure function: it takes a pair of consecutive
pitches (or None for the first pitch of a game) and returns a list of
GameStateEvents that should be published BEFORE the second pitch is published.
The replay loop is responsible for state — this module is stateless.
"""

from __future__ import annotations

from ingestion.replay_engine.events import GameStateEvent, PitchEvent
from ingestion.replay_engine.mapping import now_utc


def derive_game_state_events(
    previous_pitch: PitchEvent | None,
    current_pitch: PitchEvent,
) -> list[GameStateEvent]:
    """Return GameStateEvents implied by the transition from previous to current pitch.

    Emits in order:
    - `game_start` if previous_pitch is None (first pitch of the replay for this game)
    - `inning_start` if inning or inning_topbot changed
    - `pitching_change` if pitcher_id changed within the same half-inning
    - `scoring_play` if home_score or away_score incremented

    All emitted events use `now_utc()` for ingest_time and the current pitch's
    event_time as the canonical event timestamp.
    """
    events: list[GameStateEvent] = []
    ingest = now_utc()

    # First pitch of this game in the replay → game_start.
    if previous_pitch is None:
        events.append(
            GameStateEvent(
                event_time=current_pitch.event_time,
                ingest_time=ingest,
                game_pk=current_pitch.game_pk,
                inning=current_pitch.inning,
                inning_topbot=current_pitch.inning_topbot,
                home_score=current_pitch.home_score,
                away_score=current_pitch.away_score,
                home_pitcher_id=(
                    current_pitch.pitcher_id if current_pitch.inning_topbot == "Top" else None
                ),
                away_pitcher_id=(
                    current_pitch.pitcher_id if current_pitch.inning_topbot == "Bot" else None
                ),
                next_batter_id=current_pitch.batter_id,
                event_type="game_start",
            )
        )
        return events

    # Same game from here on. Different game_pk should not happen within one
    # replay invocation, so we treat it as a programmer error rather than a
    # game_start; the call site keys by game_pk.
    if previous_pitch.game_pk != current_pitch.game_pk:
        raise ValueError(
            f"derive_game_state_events called with mixed game_pks: "
            f"prev={previous_pitch.game_pk}, curr={current_pitch.game_pk}"
        )

    # Inning boundary: emit inning_start.
    inning_changed = (
        previous_pitch.inning != current_pitch.inning
        or previous_pitch.inning_topbot != current_pitch.inning_topbot
    )
    if inning_changed:
        events.append(
            GameStateEvent(
                event_time=current_pitch.event_time,
                ingest_time=ingest,
                game_pk=current_pitch.game_pk,
                inning=current_pitch.inning,
                inning_topbot=current_pitch.inning_topbot,
                home_score=current_pitch.home_score,
                away_score=current_pitch.away_score,
                home_pitcher_id=None,
                away_pitcher_id=None,
                next_batter_id=current_pitch.batter_id,
                event_type="inning_start",
            )
        )

    # Pitching change: same half-inning but different pitcher_id.
    # If the inning changed, the new pitcher is expected (different team batting),
    # so we don't report it as a pitching_change in the same emission.
    if not inning_changed and previous_pitch.pitcher_id != current_pitch.pitcher_id:
        is_top = current_pitch.inning_topbot == "Top"
        events.append(
            GameStateEvent(
                event_time=current_pitch.event_time,
                ingest_time=ingest,
                game_pk=current_pitch.game_pk,
                inning=current_pitch.inning,
                inning_topbot=current_pitch.inning_topbot,
                home_score=current_pitch.home_score,
                away_score=current_pitch.away_score,
                home_pitcher_id=current_pitch.pitcher_id if is_top else None,
                away_pitcher_id=current_pitch.pitcher_id if not is_top else None,
                next_batter_id=current_pitch.batter_id,
                event_type="pitching_change",
            )
        )

    # Scoring play: either score incremented.
    if (
        current_pitch.home_score > previous_pitch.home_score
        or current_pitch.away_score > previous_pitch.away_score
    ):
        events.append(
            GameStateEvent(
                event_time=current_pitch.event_time,
                ingest_time=ingest,
                game_pk=current_pitch.game_pk,
                inning=current_pitch.inning,
                inning_topbot=current_pitch.inning_topbot,
                home_score=current_pitch.home_score,
                away_score=current_pitch.away_score,
                home_pitcher_id=None,
                away_pitcher_id=None,
                next_batter_id=current_pitch.batter_id,
                event_type="scoring_play",
            )
        )

    return events
