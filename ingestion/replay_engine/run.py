"""Replay engine runner.

Reads a date (or game_pk) worth of Statcast pitches, applies configurable
noise, and publishes to Kafka at a configurable speed multiplier.

Example:
    python -m ingestion.replay_engine.run --game-date 2024-06-15 --speed 10
    python -m ingestion.replay_engine.run --game-date 2024-06-15 --game-pk 745642 --speed 1
"""

from __future__ import annotations

import os
import random
import sys
import time
from datetime import UTC, date, datetime

import click
import structlog

from ingestion.noise_injector import maybe_inject_noise
from ingestion.replay_engine.avro_publisher import AvroEventPublisher
from ingestion.replay_engine.config import config
from ingestion.replay_engine.events import CorrectionEvent, GameStateEvent, PitchEvent
from ingestion.replay_engine.game_state_deriver import derive_game_state_events
from ingestion.replay_engine.lineup_projection import DEFAULT_CACHE_PATH, LineupCache
from ingestion.replay_engine.mapping import now_utc, row_to_pitch_event
from ingestion.replay_engine.producer import EventPublisher
from ingestion.replay_engine.statcast_source import (
    filter_to_game,
    load_statcast_date,
)
from ingestion.replay_engine.uncertainty_window import (
    UncertaintyConfig,
    apply_uncertainty_window,
    compute_uncertainty_window_seconds,
)

log = structlog.get_logger(__name__)


def _configure_logging(level: str) -> None:
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            structlog.stdlib.NAME_TO_LEVEL.get(level.lower(), 20)
        ),
    )


@click.command()
@click.option(
    "--game-date",
    required=True,
    help="Date to replay, ISO format YYYY-MM-DD.",
)
@click.option(
    "--game-pk",
    type=int,
    default=None,
    help="Optional game_pk. If omitted, every game that day is replayed in order.",
)
@click.option(
    "--speed",
    type=float,
    default=None,
    help="Speed multiplier vs real time. 1.0 = real time, 60.0 = one minute per real second.",
)
@click.option(
    "--limit",
    type=int,
    default=None,
    help="Optional cap on total pitches replayed. Useful for smoke tests.",
)
@click.option(
    "--seed",
    type=int,
    default=42,
    help="RNG seed for noise injection. Keeps runs reproducible.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Build events but do not publish to Kafka. For local testing.",
)
@click.option(
    "--lineup-cache-path",
    type=click.Path(),
    default=None,
    help=(
        "Path to the precomputed lineup cache (ADR 0015). If omitted or the "
        "file does not exist, the replay proceeds with every pitch tagged "
        "lineup_state=confirmed and no BATTER_UNCERTAIN window is applied. "
        f"Default cache path: {DEFAULT_CACHE_PATH}."
    ),
)
def main(
    game_date: str,
    game_pk: int | None,
    speed: float | None,
    limit: int | None,
    seed: int,
    dry_run: bool,
    lineup_cache_path: str | None,
) -> None:
    _configure_logging(config.log_level)

    target_date = date.fromisoformat(game_date)
    effective_speed = speed if speed is not None else config.replay_default_speed
    rng = random.Random(seed)

    log.info(
        "replay starting",
        date=target_date.isoformat(),
        game_pk=game_pk,
        speed=effective_speed,
        dry_run=dry_run,
        seed=seed,
    )

    # ADR 0014 + 0015: load the precomputed lineup cache if available. If the
    # cache is missing, log a warning and proceed without the BATTER_UNCERTAIN
    # window — every pitch will be tagged lineup_state=confirmed, which is the
    # pre-Phase-2 behavior. This keeps CI and replays without precomputed
    # lineups working unchanged.
    lineup_cache = _maybe_load_lineup_cache(lineup_cache_path)
    uncertainty_config = UncertaintyConfig(base_seed=seed)

    df = load_statcast_date(target_date)
    if df.empty:
        log.error("no data for date", date=target_date.isoformat())
        sys.exit(1)

    if game_pk is not None:
        df = filter_to_game(df, game_pk)
        if df.empty:
            log.error("game_pk not found on date", game_pk=game_pk, date=target_date.isoformat())
            sys.exit(1)

    if limit is not None:
        df = df.head(limit)

    publisher = None if dry_run else _build_publisher(config.kafka_bootstrap_servers)
    _run_replay(df, publisher, effective_speed, rng, lineup_cache, uncertainty_config)

    if publisher is not None:
        publisher.flush(timeout=30.0)

    log.info("replay complete", pitches=len(df))


def _build_publisher(bootstrap_servers: str) -> EventPublisher | AvroEventPublisher:
    """Choose publisher implementation based on PUBLISHER_TYPE env var.

    PUBLISHER_TYPE=avro (default in Phase 1+) returns AvroEventPublisher with
    Schema Registry-backed Avro serialization. PUBLISHER_TYPE=json (legacy,
    Phase 0) returns the JSON EventPublisher. The env var lets us flip back
    quickly during Day 2 if the Flink integration surfaces an Avro-side bug.
    """
    publisher_type = os.environ.get("PUBLISHER_TYPE", "avro").lower()
    if publisher_type == "avro":
        log.info("publisher.selected", type="avro")
        return AvroEventPublisher(bootstrap_servers)
    elif publisher_type == "json":
        log.info("publisher.selected", type="json")
        return EventPublisher(bootstrap_servers)
    else:
        raise ValueError(f"PUBLISHER_TYPE must be 'avro' or 'json', got: {publisher_type!r}")


def _maybe_load_lineup_cache(cache_path: str | None) -> LineupCache | None:
    """Load the precomputed lineup cache or return None with a warning.

    ADR 0014 + 0015 require deterministic projections from a precomputed
    cache. If the cache is missing, the replay still runs, but every pitch
    is tagged lineup_state=confirmed (no uncertainty window applied). This
    keeps CI and ad-hoc replays without precompute_lineups working.
    """
    from pathlib import Path

    resolved_path = Path(cache_path) if cache_path else DEFAULT_CACHE_PATH
    if not resolved_path.exists():
        log.warning(
            "lineup_cache.missing",
            path=str(resolved_path),
            consequence="all pitches will be tagged lineup_state=confirmed",
            hint="run `python -m ingestion.replay_engine.precompute_lineups` to enable BATTER_UNCERTAIN",
        )
        return None

    cache = LineupCache(resolved_path)
    cache.load()
    return cache


def _run_replay(
    df,
    publisher: EventPublisher | AvroEventPublisher | None,
    speed: float,
    rng: random.Random,
    lineup_cache: LineupCache | None,
    uncertainty_config: UncertaintyConfig,
) -> None:
    pitch_count = 0
    correction_count = 0
    duplicate_count = 0
    late_count = 0
    game_state_count = 0
    uncertain_count = 0

    first_event_time: datetime = df.iloc[0]["event_time"].to_pydatetime()
    wall_clock_start = datetime.now(UTC)

    # Track the last published pitch per game_pk so the deriver can compare
    # consecutive states. Replay engine only handles one game per invocation
    # today, but keying by game_pk keeps this correct if that ever changes.
    previous_pitch_by_game: dict[int, PitchEvent] = {}

    # ADR 0014: per-game first-pitch time and sampled uncertainty window.
    # Populated lazily on the first encounter of each game_pk.
    first_pitch_time_by_game: dict[int, datetime] = {}
    uncertainty_seconds_by_game: dict[int, int] = {}

    for _idx, row in df.iterrows():
        event_time = row["event_time"].to_pydatetime()

        # Pace the replay to simulate wall-clock progression at `speed` x.
        stream_elapsed = (event_time - first_event_time).total_seconds()
        target_wall_elapsed = stream_elapsed / max(speed, 0.01)
        actual_wall_elapsed = (datetime.now(UTC) - wall_clock_start).total_seconds()
        sleep_for = target_wall_elapsed - actual_wall_elapsed
        if sleep_for > 0:
            time.sleep(min(sleep_for, 5.0))

        pitch = row_to_pitch_event(row, ingest_time=now_utc())

        # ADR 0014: tag this pitch with lineup_state and possibly substitute
        # batter_id with the projected batter (ADR 0015). On first sighting of
        # a game_pk, record its first-pitch time and sample its uncertainty
        # window length deterministically from the seed.
        if pitch.game_pk not in first_pitch_time_by_game:
            first_pitch_time_by_game[pitch.game_pk] = pitch.event_time
            uncertainty_seconds_by_game[pitch.game_pk] = compute_uncertainty_window_seconds(
                pitch.game_pk, uncertainty_config
            )
        pitch = apply_uncertainty_window(
            pitch=pitch,
            first_pitch_time=first_pitch_time_by_game[pitch.game_pk],
            uncertainty_seconds=uncertainty_seconds_by_game[pitch.game_pk],
            cache=lineup_cache,
        )
        if pitch.lineup_state == "uncertain":
            uncertain_count += 1

        # Derive game state events from the transition between the previously
        # published pitch (if any) and this one. Publish them BEFORE the pitch
        # so consumers see the state context that frames the pitch.
        previous = previous_pitch_by_game.get(pitch.game_pk)
        for gs_event in derive_game_state_events(previous, pitch):
            _publish(publisher, gs_event)
            game_state_count += 1
        previous_pitch_by_game[pitch.game_pk] = pitch

        for produced in maybe_inject_noise(
            pitch,
            late_arrival_prob=config.replay_noise_late_arrival_prob,
            duplicate_prob=config.replay_noise_duplicate_prob,
            correction_prob=config.replay_noise_correction_prob,
            rng=rng,
        ):
            _publish(publisher, produced)
            if isinstance(produced, CorrectionEvent):
                correction_count += 1
            elif produced.is_duplicate:
                duplicate_count += 1
            elif produced.is_late_arrival:
                late_count += 1
            else:
                pitch_count += 1

        if pitch_count % 50 == 0 and pitch_count > 0:
            log.info(
                "replay progress",
                pitches=pitch_count,
                duplicates=duplicate_count,
                late=late_count,
                corrections=correction_count,
                game_state_events=game_state_count,
                uncertain=uncertain_count,
            )


def _publish(
    publisher: EventPublisher | AvroEventPublisher | None,
    event: PitchEvent | CorrectionEvent | GameStateEvent,
) -> None:
    if publisher is None:
        return
    if isinstance(event, CorrectionEvent):
        publisher.publish(
            topic=config.topic_corrections_cdc,
            key=event.original_pitch_uid,
            event=event,
        )
    elif isinstance(event, GameStateEvent):
        # Key by game + event_type so consumers can partition by game while
        # still seeing all state transitions for a single game on the same
        # partition. event_type appended for human-readable kafka inspection.
        key = f"{event.game_pk}:{event.event_type}"
        publisher.publish(topic=config.topic_game_state_raw, key=key, event=event)
    else:
        key = f"{event.game_pk}:{event.at_bat_number}:{event.pitch_number}"
        publisher.publish(topic=config.topic_pitches_raw, key=key, event=event)


if __name__ == "__main__":
    main()
