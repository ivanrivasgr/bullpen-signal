"""Schema Registry client wrapper with idempotent registration and per-instance caching.

Wraps confluent_kafka.schema_registry.SchemaRegistryClient with three pieces of
project-specific behavior:

1. Idempotent registration. Schemas are canonicalized (parsed and re-serialized
   with sorted keys) before being sent to the registry, so cosmetic edits to
   .avsc files (whitespace, key ordering) don't produce new schema versions.

2. Per-instance caching. Schema IDs are cached in memory by subject so repeat
   calls to register_schema or get_serializer don't round-trip the registry.
   Cache is per-instance, not global, to keep tests isolated.

3. Project-typed errors. Underlying confluent_kafka exceptions are wrapped in
   BullpenSchemaError so call sites don't depend on the upstream package.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import structlog
from confluent_kafka.schema_registry import Schema
from confluent_kafka.schema_registry import SchemaRegistryClient as _SRClient
from confluent_kafka.schema_registry.avro import AvroSerializer
from confluent_kafka.schema_registry.error import SchemaRegistryError

log = structlog.get_logger(__name__)

DEFAULT_SCHEMA_REGISTRY_URL = "http://localhost:18081"


class BullpenSchemaError(Exception):
    """Raised for any Schema Registry interaction failure.

    Wraps the underlying confluent_kafka SchemaRegistryError so consumers of
    this module never need to import from confluent_kafka directly.
    """


def _canonicalize_avro_schema(schema_path: Path) -> str:
    """Return a stable JSON serialization of an Avro schema file.

    Two .avsc files that differ only in whitespace or key ordering produce
    identical canonical strings. This is what enables idempotent registration:
    register_schema can compare the canonical form against what's already in
    the registry and skip the round-trip if they match.
    """
    with schema_path.open("r", encoding="utf-8") as f:
        schema_dict = json.load(f)
    return json.dumps(schema_dict, sort_keys=True, separators=(",", ":"))


class SchemaRegistryClient:
    """Project wrapper around confluent_kafka's SchemaRegistryClient.

    Reads URL from KAFKA_SCHEMA_REGISTRY_URL env var (default: localhost:18081).
    Caches schema IDs per subject for the lifetime of the instance.
    """

    def __init__(self, url: str | None = None) -> None:
        self._url = url or os.environ.get("KAFKA_SCHEMA_REGISTRY_URL", DEFAULT_SCHEMA_REGISTRY_URL)
        self._client = _SRClient({"url": self._url})
        self._schema_id_cache: dict[str, int] = {}
        log.info("schema_registry.client.init", url=self._url)

    def register_schema(self, subject: str, schema_path: str | Path) -> int:
        """Register an Avro schema file under a subject. Idempotent.

        If the same canonical schema is already registered under the subject,
        returns the existing schema ID without writing to the registry. Hit on
        the per-instance cache returns immediately; cache miss resolves via
        the registry's own dedup (register_schema returns existing ID if the
        canonical form matches).
        """
        path = Path(schema_path)
        if not path.is_file():
            raise BullpenSchemaError(f"Avro schema file not found: {path}")

        if subject in self._schema_id_cache:
            cached_id = self._schema_id_cache[subject]
            log.debug(
                "schema_registry.register.cache_hit",
                subject=subject,
                schema_id=cached_id,
            )
            return cached_id

        canonical = _canonicalize_avro_schema(path)
        schema = Schema(canonical, schema_type="AVRO")

        try:
            schema_id = self._client.register_schema(subject, schema)
        except SchemaRegistryError as e:
            raise BullpenSchemaError(
                f"Failed to register schema for subject '{subject}': {e}"
            ) from e

        self._schema_id_cache[subject] = schema_id
        log.info(
            "schema_registry.register.ok",
            subject=subject,
            schema_id=schema_id,
            schema_path=str(path),
        )
        return schema_id

    def get_serializer(
        self,
        subject: str,
        schema_path: str | Path,
        to_dict: Any = None,
    ) -> AvroSerializer:
        """Return an AvroSerializer ready to wire into a Kafka producer.

        Registers the schema as a side effect (idempotent). The returned
        serializer is configured to use the same registry instance, so
        produce-time lookups use the same connection.
        """
        # Side-effect: ensure schema is registered and cached.
        self.register_schema(subject, schema_path)

        canonical = _canonicalize_avro_schema(Path(schema_path))
        return AvroSerializer(
            schema_registry_client=self._client,
            schema_str=canonical,
            to_dict=to_dict,
        )

    @property
    def url(self) -> str:
        return self._url
