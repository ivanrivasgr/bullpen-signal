"""Thin wrapper around confluent_kafka.Producer.

JSON serialization for Phase 0; Phase 1 moves to Avro with the schema registry.
Keeping it simple so the first milestone ships fast.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import structlog
from confluent_kafka import Producer
from pydantic import BaseModel

log = structlog.get_logger(__name__)


class EventPublisher:
    def __init__(self, bootstrap_servers: str, client_id: str = "replay-engine") -> None:
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
        self._delivered = 0
        self._failed = 0

    def publish(self, topic: str, key: str, event: BaseModel) -> None:
        payload = event.model_dump(mode="json")
        self._producer.produce(
            topic=topic,
            key=key.encode("utf-8"),
            value=json.dumps(payload, default=_json_default).encode("utf-8"),
            on_delivery=self._on_delivery,
        )
        # Non-blocking poll to drive delivery callbacks.
        self._producer.poll(0)

    def flush(self, timeout: float = 10.0) -> int:
        remaining = self._producer.flush(timeout)
        log.info(
            "producer flushed",
            delivered=self._delivered,
            failed=self._failed,
            remaining=remaining,
        )
        return remaining

    def _on_delivery(self, err: Any, msg: Any) -> None:
        if err is not None:
            self._failed += 1
            log.error("delivery failed", error=str(err), topic=msg.topic() if msg else None)
        else:
            self._delivered += 1


def _json_default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")
