"""Apply the BATTER_UNCERTAIN window to historical pitch events.

Implements the runtime side of ADR 0014. Given a stream of pitch events
in event-time order, this module decides which of those events should
be tagged `lineup_state = uncertain` (with a projected batter) versus
`lineup_state = confirmed` (with the real batter).

The replay engine reproduces historical Statcast data. Statcast has no
pitches before first pitch, so the ADR 0014 concept of "uncertainty
window before first pitch" is materialized here as "the first K seconds
of the game where we simulate that lineup confirmation arrived late".
This corresponds to the ADR 0014 acknowledgment that lineup confirmation
"occasionally lands after the game has already started" — those are
exactly the simulated games we generate here.

The window duration K is sampled deterministically from a per-game seed
derived from game_pk and a configurable base seed. Two replay runs with
the same seed produce byte-identical lineup_state tagging.

Distribution choice (ADR 0014 spirit, not letter):
- 85% of games: K = 0. Lineup confirmed before first pitch. Every pitch
  is `confirmed`. This is the modal production case.
- 15% of games: K sampled from an exponential distribution clipped to
  [60, 1800] seconds. This represents late confirmation events.

The 15% target rate is configurable but defaults to the value above to
match the "occasionally late" framing in ADR 0014.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from random import Random

import structlog

from ingestion.replay_engine.events import PitchEvent
from ingestion.replay_engine.lineup_projection import LineupCache, compute_projected_batter

log = structlog.get_logger(__name__)

# Defaults — calibrated to ADR 0014's "occasionally late" framing.
DEFAULT_LATE_GAME_RATE = 0.15
DEFAULT_MIN_WINDOW_SECONDS = 60
DEFAULT_MAX_WINDOW_SECONDS = 1800
DEFAULT_EXPONENTIAL_MEAN_SECONDS = 600


@dataclass(frozen=True)
class UncertaintyConfig:
    """Tunables for the uncertainty-window sampler.

    Defaults match ADR 0014 framing. Override for tests or for replay
    runs that want a heavier or lighter uncertainty signal.
    """

    base_seed: int = 42
    late_game_rate: float = DEFAULT_LATE_GAME_RATE
    min_window_seconds: int = DEFAULT_MIN_WINDOW_SECONDS
    max_window_seconds: int = DEFAULT_MAX_WINDOW_SECONDS
    exponential_mean_seconds: int = DEFAULT_EXPONENTIAL_MEAN_SECONDS


def compute_uncertainty_window_seconds(
    game_pk: int,
    config: UncertaintyConfig | None = None,
) -> int:
    """Return the uncertainty window length (in seconds) for one game.

    Deterministic per game_pk + config.base_seed. The same inputs always
    produce the same output, which keeps replay runs reproducible per
    ADR 0014.

    Returns 0 for the modal case (lineup confirmed before first pitch).
    Returns a value in [min_window_seconds, max_window_seconds] for
    games that simulate late confirmation.
    """
    if config is None:
        config = UncertaintyConfig()
    # Per-game RNG so games are independent and the global ordering of
    # replay events does not change the window for any specific game.
    # Combine game_pk and base_seed into a single int seed — Random does
    # not accept tuples. Bit-shift gives us a unique deterministic seed
    # per (game_pk, base_seed) pair without collisions in any realistic range.
    combined_seed = (game_pk << 32) ^ config.base_seed
    rng = Random(combined_seed)

    # First flip: is this a late-lineup game at all?
    if rng.random() >= config.late_game_rate:
        return 0

    # Second draw: how late, sampled from clipped exponential.
    # expovariate(lambda) where mean = 1/lambda. We pass 1/mean.
    raw_seconds = rng.expovariate(1.0 / config.exponential_mean_seconds)
    clipped = max(
        config.min_window_seconds,
        min(config.max_window_seconds, int(raw_seconds)),
    )
    return clipped


def apply_uncertainty_window(
    pitch: PitchEvent,
    first_pitch_time: datetime,
    uncertainty_seconds: int,
    cache: LineupCache | None,
    lineup_position: int | None = None,
) -> PitchEvent:
    """Return a copy of `pitch` with `lineup_state` and possibly `batter_id` adjusted.

    If the pitch's event_time is within `uncertainty_seconds` of
    first_pitch_time, the pitch is tagged `lineup_state = uncertain` and
    its batter_id is replaced with the projected batter from
    `compute_projected_batter`. Otherwise it is tagged `confirmed` and
    returned with the original batter intact.

    `cache` and `lineup_position` are required to compute the projection
    inside the uncertainty window. If `cache` is None (e.g. testing) or
    the projection itself returns None (cache miss across all layers per
    ADR 0015), the pitch keeps its original `batter_id` and is still
    tagged `uncertain` — losing the projected-batter signal is a
    documented downstream concern, not a reason to mislabel state.

    `lineup_position` is the position in the batting order. If not
    provided, the function falls back to the pitch's at_bat_number
    modulo 9 (1-indexed), which is a reasonable approximation for
    historical replay where lineup_position is not explicitly recorded.
    """
    if uncertainty_seconds <= 0:
        return pitch.model_copy(update={"lineup_state": "confirmed"})

    window_end = first_pitch_time + timedelta(seconds=uncertainty_seconds)
    if pitch.event_time >= window_end:
        return pitch.model_copy(update={"lineup_state": "confirmed"})

    # Inside the uncertainty window: tag as uncertain and try to project.
    # If projection fails (cache miss across all ADR 0015 layers), leave
    # projected_batter_id as None rather than copying the real batter — a
    # failed projection is not the same as "projected the right batter".
    projected_batter_id = None
    if cache is not None:
        position = (
            lineup_position
            if lineup_position is not None
            else _approximate_lineup_position(pitch.at_bat_number)
        )
        team_id = _infer_batting_team_id(pitch)
        if team_id is not None:
            projected = compute_projected_batter(
                team_id=team_id,
                lineup_position=position,
                projection_date=pitch.event_time.date(),
                cache=cache,
            )
            if projected is not None:
                projected_batter_id = projected

    # Preserve the observed batter (ground truth) in batter_id; record the
    # projection in projected_batter_id. ADR 0020 reverses the earlier design
    # that overwrote batter_id with the projection — destroying ground truth
    # made reconciliation impossible to compute downstream.
    return pitch.model_copy(
        update={
            "lineup_state": "uncertain",
            "projected_batter_id": projected_batter_id,
        }
    )


def _approximate_lineup_position(at_bat_number: int) -> int:
    """Best-effort 1-indexed lineup position from at_bat_number.

    Statcast does not record lineup position per pitch event. The
    at_bat_number cycles through the order, so position = ((at_bat - 1)
    % 9) + 1 is a reasonable approximation for early-game at-bats. This
    breaks down after pinch hitters or double-switches, which is a
    documented limitation, not a bug — projections during uncertainty
    are inherently approximate.
    """
    if at_bat_number < 1:
        return 1
    return ((at_bat_number - 1) % 9) + 1


def _infer_batting_team_id(pitch: PitchEvent) -> int | None:
    """Return the team_id of the club currently batting.

    In the top of an inning the away team bats; in the bottom the home
    team bats. The team_ids are threaded onto the pitch event from the
    Statcast home_team/away_team abbreviations (see mapping.py and
    team_lookup.py).

    Returns None if the relevant team_id was not threaded (e.g. an event
    built without team context, or an abbreviation missing from the
    reference map). A None return skips projection and leaves
    projected_batter_id None — the same graceful degradation as a cache
    miss, so no pitch is ever mislabeled on account of a missing team_id.
    """
    if pitch.inning_topbot == "Top":
        return pitch.away_team_id
    return pitch.home_team_id
