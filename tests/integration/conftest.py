"""Shared fixtures for integration tests.

These fixtures assume the local Redpanda + Schema Registry stack is up.
The `_require_stack` autouse fixture skips the entire test if the stack
is unreachable, so a developer running `pytest -m integration` without
having `make up`-ed gets a clean skip instead of a test failure.
"""

from __future__ import annotations

import os
import socket
import subprocess
import time
from collections.abc import Iterator

import pytest
from confluent_kafka import Consumer, TopicPartition
from confluent_kafka.schema_registry import SchemaRegistryClient as _SRClient
from confluent_kafka.schema_registry.avro import AvroDeserializer

BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092")
SCHEMA_REGISTRY_URL = os.environ.get("KAFKA_SCHEMA_REGISTRY_URL", "http://localhost:18081")
REDPANDA_CONTAINER = "bullpen-redpanda"


def _is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture(autouse=True)
def _require_stack() -> None:
    """Skip the integration test if the local stack isn't reachable."""
    host, _, port_str = BOOTSTRAP_SERVERS.partition(":")
    if not _is_port_open(host, int(port_str)):
        pytest.skip(f"Kafka not reachable at {BOOTSTRAP_SERVERS}; run `make up` first.")

    sr_host = SCHEMA_REGISTRY_URL.replace("http://", "").replace("https://", "")
    sr_host, _, sr_port_str = sr_host.partition(":")
    sr_port_str = sr_port_str.split("/")[0]
    if not _is_port_open(sr_host, int(sr_port_str)):
        pytest.skip(f"Schema Registry not reachable at {SCHEMA_REGISTRY_URL}; run `make up` first.")


def _rpk(*args: str) -> subprocess.CompletedProcess[str]:
    """Invoke `rpk` inside the redpanda container."""
    return subprocess.run(
        ["docker", "exec", REDPANDA_CONTAINER, "rpk", *args],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def clean_topic() -> Iterator[callable]:
    """Factory fixture: returns a function that deletes-and-recreates a topic.

    Cleanup happens *before* the test, not after, so any debugging artifacts
    survive the test run for inspection in Redpanda Console.
    """

    def _clean(topic_name: str, partitions: int = 3, replicas: int = 1) -> None:
        # Delete is best-effort; topic might not exist yet.
        _rpk("topic", "delete", topic_name)
        # Brief wait for delete to propagate before recreate.
        time.sleep(0.5)
        result = _rpk(
            "topic",
            "create",
            topic_name,
            "--partitions",
            str(partitions),
            "--replicas",
            str(replicas),
        )
        if result.returncode != 0 and "already exists" not in result.stderr.lower():
            raise RuntimeError(f"Failed to recreate topic {topic_name}: {result.stderr}")

    yield _clean


@pytest.fixture
def avro_consumer_factory():
    """Factory: returns a Consumer + AvroDeserializer ready to read a topic from offset 0."""
    sr_client = _SRClient({"url": SCHEMA_REGISTRY_URL})
    consumers: list[Consumer] = []

    def _make(topic: str, group_suffix: str) -> tuple[Consumer, AvroDeserializer]:
        consumer = Consumer(
            {
                "bootstrap.servers": BOOTSTRAP_SERVERS,
                "group.id": f"integration-test-{topic}-{group_suffix}-{int(time.time() * 1000)}",
                "auto.offset.reset": "earliest",
                "enable.auto.commit": False,
            }
        )
        # Assign all partitions and seek to beginning so we read everything,
        # regardless of consumer-group state from previous runs.
        metadata = consumer.list_topics(topic, timeout=5.0)
        if topic not in metadata.topics or metadata.topics[topic].error:
            raise RuntimeError(f"Topic {topic} not available")
        partitions = [TopicPartition(topic, p, 0) for p in metadata.topics[topic].partitions]
        consumer.assign(partitions)

        deserializer = AvroDeserializer(schema_registry_client=sr_client)
        consumers.append(consumer)
        return consumer, deserializer

    yield _make

    for c in consumers:
        c.close()


def consume_until_quiet(
    consumer: Consumer,
    deserializer: AvroDeserializer,
    *,
    quiet_window_seconds: float = 2.0,
    max_total_seconds: float = 30.0,
) -> list[dict]:
    """Poll until no new messages arrive for `quiet_window_seconds`.

    Returns the deserialized payloads (Avro values) in the order received.
    A hard cap of `max_total_seconds` prevents test hangs.
    """
    from confluent_kafka.serialization import MessageField, SerializationContext

    payloads: list[dict] = []
    started = time.time()
    last_msg_time = time.time()

    while True:
        if time.time() - started > max_total_seconds:
            break
        if time.time() - last_msg_time > quiet_window_seconds and payloads:
            break

        msg = consumer.poll(timeout=0.5)
        if msg is None:
            continue
        if msg.error():
            continue

        ctx = SerializationContext(msg.topic(), MessageField.VALUE)
        value = deserializer(msg.value(), ctx)
        if value is not None:
            payloads.append(value)
            last_msg_time = time.time()

    return payloads
