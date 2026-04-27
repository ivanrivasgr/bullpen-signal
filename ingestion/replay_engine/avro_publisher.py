"""Avro-serialized publisher for the replay stream.

Wraps confluent_kafka.Producer with AvroSerializer instances obtained from the
project's SchemaRegistryClient wrapper. Schemas are registered eagerly at
construction time so any registry-side issue (unreachable, incompatible) is
surfaced at startup rather than mid-replay.

Wire format: Confluent magic byte (0x00) + 4-byte schema_id (big-endian) +
Avro binary payload. Keys are plain UTF-8 strings (not Avro-encoded) so the
key is visible to partitioning logic without a deserializer.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import structlog
from confluent_kafka import Producer
from confluent_kafka.serialization import MessageField, SerializationContext

from ingestion.replay_engine.events import (
    CorrectionEvent,
    GameStateEvent,
    PitchEvent,
)
from streaming.schema_registry import SchemaRegistryClient

log = structlog.get_logger(__name__)

# Default schema paths relative to repo root. Override via constructor for tests.
_DEFAULT_SCHEMA_DIR = Path("streaming/schemas")
_PITCH_EVENT_SCHEMA = _DEFAULT_SCHEMA_DIR / "pitch_event.avsc"
_GAME_STATE_SCHEMA = _DEFAULT_SCHEMA_DIR / "game_state_event.avsc"
_CORRECTION_SCHEMA = _DEFAULT_SCHEMA_DIR / "correction_event.avsc"


def _datetime_to_millis(dt: datetime) -> int:
    """Convert a Python datetime to Avro timestamp-millis (int milliseconds since epoch).

    Pydantic stores datetimes as timezone-aware (we set ingest_time with UTC).
    fastavro's logical type encoder for timestamp-millis expects an int, not a
    datetime, when going through AvroSerializer with a manually-constructed dict.
    """
    return int(dt.timestamp() * 1000)


def pitch_event_to_avro_dict(event: PitchEvent) -> dict[str, Any]:
    """Map a PitchEvent Pydantic model to a dict matching pitch_event.avsc."""
    return {
        "event_time": _datetime_to_millis(event.event_time),
        "ingest_time": _datetime_to_millis(event.ingest_time),
        "game_pk": event.game_pk,
        "at_bat_number": event.at_bat_number,
        "pitch_number": event.pitch_number,
        "inning": event.inning,
        "inning_topbot": event.inning_topbot,
        "pitcher_id": event.pitcher_id,
        "batter_id": event.batter_id,
        "pitch_type": event.pitch_type,
        "release_speed": event.release_speed,
        "release_spin_rate": event.release_spin_rate,
        "plate_x": event.plate_x,
        "plate_z": event.plate_z,
        "zone": event.zone,
        "balls": event.balls,
        "strikes": event.strikes,
        "outs_when_up": event.outs_when_up,
        "on_1b": event.on_1b,
        "on_2b": event.on_2b,
        "on_3b": event.on_3b,
        "description": event.description,
        "events": event.events,
        "home_score": event.home_score,
        "away_score": event.away_score,
        "is_late_arrival": event.is_late_arrival,
        "is_duplicate": event.is_duplicate,
        "correction_of": event.correction_of,
    }


def game_state_event_to_avro_dict(event: GameStateEvent) -> dict[str, Any]:
    """Map a GameStateEvent Pydantic model to a dict matching game_state_event.avsc."""
    return {
        "event_time": _datetime_to_millis(event.event_time),
        "ingest_time": _datetime_to_millis(event.ingest_time),
        "game_pk": event.game_pk,
        "inning": event.inning,
        "inning_topbot": event.inning_topbot,
        "home_score": event.home_score,
        "away_score": event.away_score,
        "home_pitcher_id": event.home_pitcher_id,
        "away_pitcher_id": event.away_pitcher_id,
        "next_batter_id": event.next_batter_id,
        "event_type": event.event_type,
    }


def correction_event_to_avro_dict(event: CorrectionEvent) -> dict[str, Any]:
    """Map a CorrectionEvent Pydantic model to a dict matching correction_event.avsc."""
    return {
        "event_time": _datetime_to_millis(event.event_time),
        "ingest_time": _datetime_to_millis(event.ingest_time),
        "game_pk": event.game_pk,
        "original_pitch_uid": event.original_pitch_uid,
        "field": event.field,
        "old_value": event.old_value,
        "new_value": event.new_value,
    }


class AvroEventPublisher:
    """Kafka publisher that serializes events as Avro using Schema Registry.

    Schemas for pitches, game state, and corrections are registered at
    construction time. Each call to publish() picks the right serializer
    based on the event's Python type.
    """

    def __init__(
        self,
        bootstrap_servers: str,
        schema_registry_url: str | None = None,
        client_id: str = "replay-engine",
        schema_dir: Path | None = None,
    ) -> None:
        schema_dir = schema_dir or _DEFAULT_SCHEMA_DIR

        self._producer = Producer(
            {
                "bootstrap.servers": bootstrap_servers,
                "client.id": client_id,
                "enable.idempotence": True,
                "acks": "all",
                "compression.type": "zstd",
                "linger.ms": 5,
            }
        )

        self._sr = SchemaRegistryClient(url=schema_registry_url)

        # Register and build serializers eagerly. Failure here is a startup
        # error, not a per-event surprise.
        self._pitch_serializer = self._sr.get_serializer(
            subject="pitches.raw-value",
            schema_path=schema_dir / "pitch_event.avsc",
            to_dict=lambda obj, ctx: obj,  # we already pass dicts
        )
        self._game_state_serializer = self._sr.get_serializer(
            subject="game_state.raw-value",
            schema_path=schema_dir / "game_state_event.avsc",
            to_dict=lambda obj, ctx: obj,
        )
        self._correction_serializer = self._sr.get_serializer(
            subject="corrections.cdc-value",
            schema_path=schema_dir / "correction_event.avsc",
            to_dict=lambda obj, ctx: obj,
        )

        self._delivered = 0
        self._failed = 0
        log.info(
            "avro_publisher.init",
            bootstrap_servers=bootstrap_servers,
            schema_registry_url=self._sr.url,
        )

    def publish(
        self,
        topic: str,
        key: str,
        event: PitchEvent | GameStateEvent | CorrectionEvent,
    ) -> None:
        """Publish an event with Avro serialization. Non-blocking."""
        if isinstance(event, PitchEvent):
            payload_dict = pitch_event_to_avro_dict(event)
            serializer = self._pitch_serializer
        elif isinstance(event, GameStateEvent):
            payload_dict = game_state_event_to_avro_dict(event)
            serializer = self._game_state_serializer
        elif isinstance(event, CorrectionEvent):
            payload_dict = correction_event_to_avro_dict(event)
            serializer = self._correction_serializer
        else:
            raise TypeError(f"AvroEventPublisher cannot serialize {type(event).__name__}")

        ctx = SerializationContext(topic, MessageField.VALUE)
        value_bytes = serializer(payload_dict, ctx)

        self._producer.produce(
            topic=topic,
            key=key.encode("utf-8"),
            value=value_bytes,
            on_delivery=self._on_delivery,
        )
        self._producer.poll(0)

    def flush(self, timeout: float = 10.0) -> int:
        remaining = self._producer.flush(timeout)
        log.info(
            "avro_publisher.flushed",
            delivered=self._delivered,
            failed=self._failed,
            remaining=remaining,
        )
        return remaining

    def _on_delivery(self, err: Any, msg: Any) -> None:
        if err is not None:
            self._failed += 1
            log.error(
                "avro_publisher.delivery_failed",
                error=str(err),
                topic=msg.topic() if msg else None,
            )
        else:
            self._delivered += 1
