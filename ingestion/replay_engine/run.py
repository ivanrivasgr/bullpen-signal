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
from ingestion.replay_engine.events import CorrectionEvent, PitchEvent
from ingestion.replay_engine.mapping import now_utc, row_to_pitch_event
from ingestion.replay_engine.producer import EventPublisher
from ingestion.replay_engine.statcast_source import (
    filter_to_game,
    load_statcast_date,
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
            structlog.stdlib._NAME_TO_LEVEL.get(level.lower(), 20)
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
def main(
    game_date: str,
    game_pk: int | None,
    speed: float | None,
    limit: int | None,
    seed: int,
    dry_run: bool,
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
    _run_replay(df, publisher, effective_speed, rng)

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


def _run_replay(
    df, publisher: EventPublisher | AvroEventPublisher | None, speed: float, rng: random.Random
) -> None:
    pitch_count = 0
    correction_count = 0
    duplicate_count = 0
    late_count = 0

    first_event_time: datetime = df.iloc[0]["event_time"].to_pydatetime()
    wall_clock_start = datetime.now(UTC)

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
            )


def _publish(
    publisher: EventPublisher | AvroEventPublisher | None, event: PitchEvent | CorrectionEvent
) -> None:
    if publisher is None:
        return
    if isinstance(event, CorrectionEvent):
        publisher.publish(
            topic=config.topic_corrections_cdc,
            key=event.original_pitch_uid,
            event=event,
        )
    else:
        key = f"{event.game_pk}:{event.at_bat_number}:{event.pitch_number}"
        publisher.publish(topic=config.topic_pitches_raw, key=key, event=event)


if __name__ == "__main__":
    main()
