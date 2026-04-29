"""Phase 1 Day 2 smoke job: PyFlink reads pitches.raw and counts per-pitcher in 1-minute windows.

This job exists to prove the wiring works end-to-end:
  Replay engine -> Kafka (Avro) -> Flink source -> watermarks -> keyed window -> print sink

It is not the production fatigue job. The production jobs in
streaming/flink_jobs/{fatigue,leverage,matchup,alert_orchestrator}/ build on
the patterns established here.

Why a custom Avro decoder instead of ConfluentRegistryAvroDeserializationSchema:
  PyFlink does not expose a native Python API for the Confluent registry
  deserializer. The Java class can be reached via py4j gateway calls but
  that adds 60-90 minutes of plumbing for no Phase 1 benefit. Instead we
  read the magic byte + schema_id ourselves, look the schema up via the
  project's SchemaRegistryClient wrapper, and decode the binary payload
  with fastavro. If perf becomes an issue in Phase 2 we migrate.

Run with:
  bash streaming/flink_jobs/_smoke/submit.sh

Output appears in the TaskManager stdout:
  docker logs bullpen-flink-tm | tail -50
"""

from __future__ import annotations

import io
import struct

import fastavro
from confluent_kafka.schema_registry import SchemaRegistryClient as ConfluentSRClient
from pyflink.common import WatermarkStrategy
from pyflink.common.serialization import SimpleStringSchema
from pyflink.common.typeinfo import Types
from pyflink.datastream import StreamExecutionEnvironment
from pyflink.datastream.connectors.kafka import KafkaOffsetsInitializer, KafkaSource
from pyflink.datastream.formats.avro import (
    AvroRowDeserializationSchema,  # noqa: F401  # imported to ensure JAR loaded
)

# Inside the container these resolve to the docker-compose service names.
KAFKA_BOOTSTRAP = "redpanda:29092"
SCHEMA_REGISTRY = "http://redpanda:18081"
TOPIC = "pitches.raw"

# Schema cache: schema_id -> parsed avro schema dict.
# Module-level so it persists across calls within the same TaskManager process.
_schema_cache: dict[int, dict] = {}
_sr_client: ConfluentSRClient | None = None


def _get_sr_client() -> ConfluentSRClient:
    """Lazily build a Schema Registry client. Per-process, not per-message."""
    global _sr_client
    if _sr_client is None:
        _sr_client = ConfluentSRClient({"url": SCHEMA_REGISTRY})
    return _sr_client


def _decode_avro_message(raw: bytes) -> dict | None:
    """Decode a Confluent-framed Avro message: magic byte + schema_id + payload.

    Returns the decoded record as a dict, or None if the message is malformed
    or the schema lookup fails. Logging is to stdout so it shows up in the
    TaskManager logs.
    """
    if len(raw) < 5:
        return None
    magic, schema_id = struct.unpack(">bI", raw[:5])
    if magic != 0:
        return None
    try:
        if schema_id not in _schema_cache:
            schema_str = _get_sr_client().get_schema(schema_id).schema_str
            _schema_cache[schema_id] = fastavro.parse_schema(
                fastavro.schema.parse_schema_from_string(schema_str)
                if hasattr(fastavro.schema, "parse_schema_from_string")
                else __import__("json").loads(schema_str)
            )
        return fastavro.schemaless_reader(io.BytesIO(raw[5:]), _schema_cache[schema_id])
    except Exception as exc:
        print(f"[smoke_job] decode failure schema_id={schema_id}: {exc}", flush=True)
        return None


def _decode_to_pitcher_event_time(raw: bytes) -> tuple[int, int] | None:
    """Project a raw Kafka value to (pitcher_id, event_time_millis).

    Used as a flat_map: returns either a single-element list with the tuple
    or an empty list if decode failed (drop the message).
    """
    record = _decode_avro_message(raw)
    if record is None:
        return None
    pitcher_id = record.get("pitcher_id")
    event_time = record.get("event_time")
    if pitcher_id is None or event_time is None:
        return None
    return (int(pitcher_id), int(event_time))


def main() -> None:
    env = StreamExecutionEnvironment.get_execution_environment()
    env.set_parallelism(1)  # one slot, one window operator — easy to inspect

    source = (
        KafkaSource.builder()
        .set_bootstrap_servers(KAFKA_BOOTSTRAP)
        .set_topics(TOPIC)
        .set_group_id("bullpen-smoke-job")
        .set_starting_offsets(KafkaOffsetsInitializer.latest())
        .set_value_only_deserializer(SimpleStringSchema())  # we receive raw bytes as str-ish
        .build()
    )

    # Watermarks: bounded out-of-orderness 2 minutes. Real Statcast streams
    # have late arrivals from Statcast corrections; 2 min absorbs that.
    watermark_strategy = WatermarkStrategy.no_watermarks()  # smoke job: no watermarks needed
    # The production fatigue job uses:
    #   WatermarkStrategy.for_bounded_out_of_orderness(Duration.of_seconds(120))

    raw_stream = env.from_source(
        source,
        watermark_strategy,
        source_name="pitches.raw source",
    )

    # SimpleStringSchema gives us str; but Confluent framing is binary bytes.
    # Convert back: encode as latin-1 to roundtrip every byte value.
    decoded = raw_stream.map(
        lambda s: _decode_to_pitcher_event_time(s.encode("latin-1") if isinstance(s, str) else s),
        output_type=Types.TUPLE([Types.LONG(), Types.LONG()]),
    ).filter(lambda t: t is not None)

    # For the smoke job we don't window — we just print every received pitch
    # tagged with its pitcher_id. The TaskManager stdout shows the pitches
    # decoded with field names, which is the wire-format proof we want.
    decoded.map(
        lambda t: f"[smoke_job] pitcher={t[0]} event_time_ms={t[1]}",
        output_type=Types.STRING(),
    ).print()

    env.execute("bullpen-signal smoke job: pitches.raw decoder")


if __name__ == "__main__":
    main()
