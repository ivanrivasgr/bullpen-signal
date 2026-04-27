"""Unit tests for streaming.schema_registry.client.

These tests exercise the wrapper's behavior against a mocked
confluent_kafka SchemaRegistryClient. They do not require the live
Redpanda Schema Registry to be running. An integration test against the
real registry will be added in M1 Day 2 alongside the producer wiring.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from streaming.schema_registry.client import (
    BullpenSchemaError,
    SchemaRegistryClient,
    _canonicalize_avro_schema,
)


@pytest.fixture
def sample_avsc(tmp_path: Path) -> Path:
    """Write a minimal valid Avro schema to a temp file."""
    schema = {
        "type": "record",
        "name": "TestEvent",
        "namespace": "bullpen.signal.test",
        "fields": [
            {"name": "id", "type": "long"},
            {"name": "label", "type": ["null", "string"], "default": None},
        ],
    }
    schema_path = tmp_path / "test_event.avsc"
    schema_path.write_text(json.dumps(schema, indent=2))
    return schema_path


@pytest.fixture
def reformatted_avsc(tmp_path: Path) -> Path:
    """Same logical schema as sample_avsc but with different whitespace and key order."""
    schema = {
        "namespace": "bullpen.signal.test",
        "name": "TestEvent",
        "fields": [
            {"type": "long", "name": "id"},
            {"default": None, "name": "label", "type": ["null", "string"]},
        ],
        "type": "record",
    }
    schema_path = tmp_path / "test_event_reformatted.avsc"
    schema_path.write_text(json.dumps(schema))
    return schema_path


class TestCanonicalize:
    def test_two_equivalent_schemas_produce_same_canonical_form(
        self, sample_avsc: Path, reformatted_avsc: Path
    ) -> None:
        assert _canonicalize_avro_schema(sample_avsc) == _canonicalize_avro_schema(reformatted_avsc)

    def test_canonical_form_is_compact_and_sorted(self, sample_avsc: Path) -> None:
        canonical = _canonicalize_avro_schema(sample_avsc)
        assert ", " not in canonical
        assert ": " not in canonical
        assert canonical.index('"fields"') < canonical.index('"name"')


class TestRegisterSchema:
    def test_fresh_registration_returns_schema_id(self, sample_avsc: Path) -> None:
        with patch("streaming.schema_registry.client._SRClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.register_schema.return_value = 42
            mock_client_cls.return_value = mock_client

            client = SchemaRegistryClient(url="http://fake:18081")
            schema_id = client.register_schema("test-value", sample_avsc)

            assert schema_id == 42
            mock_client.register_schema.assert_called_once()

    def test_double_registration_is_idempotent_via_cache(self, sample_avsc: Path) -> None:
        """Second call hits the in-memory cache and never touches the registry."""
        with patch("streaming.schema_registry.client._SRClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.register_schema.return_value = 7
            mock_client_cls.return_value = mock_client

            client = SchemaRegistryClient(url="http://fake:18081")
            sid1 = client.register_schema("test-value", sample_avsc)
            sid2 = client.register_schema("test-value", sample_avsc)

            assert sid1 == sid2 == 7
            assert mock_client.register_schema.call_count == 1

    def test_idempotent_across_cosmetic_schema_edits(
        self, sample_avsc: Path, reformatted_avsc: Path
    ) -> None:
        with patch("streaming.schema_registry.client._SRClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.register_schema.return_value = 99
            mock_client_cls.return_value = mock_client

            client = SchemaRegistryClient(url="http://fake:18081")
            sid1 = client.register_schema("test-value", sample_avsc)
            sid2 = client.register_schema("test-value", reformatted_avsc)

            assert sid1 == sid2 == 99
            assert mock_client.register_schema.call_count == 1

    def test_missing_schema_file_raises_clear_error(self, tmp_path: Path) -> None:
        client = SchemaRegistryClient(url="http://fake:18081")
        with pytest.raises(BullpenSchemaError, match="not found"):
            client.register_schema("test-value", tmp_path / "does_not_exist.avsc")

    def test_registry_failure_wraps_in_bullpen_error(self, sample_avsc: Path) -> None:
        from confluent_kafka.schema_registry.error import SchemaRegistryError

        with patch("streaming.schema_registry.client._SRClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.register_schema.side_effect = SchemaRegistryError(
                http_status_code=409,
                error_code=42201,
                error_message="incompatible",
            )
            mock_client_cls.return_value = mock_client

            client = SchemaRegistryClient(url="http://fake:18081")
            with pytest.raises(BullpenSchemaError, match="test-value"):
                client.register_schema("test-value", sample_avsc)


class TestEnvVarConfig:
    def test_url_defaults_to_localhost_18081(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("KAFKA_SCHEMA_REGISTRY_URL", raising=False)
        with patch("streaming.schema_registry.client._SRClient"):
            client = SchemaRegistryClient()
            assert client.url == "http://localhost:18081"

    def test_url_reads_from_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KAFKA_SCHEMA_REGISTRY_URL", "http://other-host:18081")
        with patch("streaming.schema_registry.client._SRClient"):
            client = SchemaRegistryClient()
            assert client.url == "http://other-host:18081"

    def test_explicit_url_overrides_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KAFKA_SCHEMA_REGISTRY_URL", "http://env-host:18081")
        with patch("streaming.schema_registry.client._SRClient"):
            client = SchemaRegistryClient(url="http://explicit:18081")
            assert client.url == "http://explicit:18081"


class TestGetSerializer:
    def test_returns_avro_serializer_and_registers_as_side_effect(self, sample_avsc: Path) -> None:
        from confluent_kafka.schema_registry.avro import AvroSerializer

        with patch("streaming.schema_registry.client._SRClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.register_schema.return_value = 11
            mock_client_cls.return_value = mock_client

            client = SchemaRegistryClient(url="http://fake:18081")
            serializer = client.get_serializer("test-value", sample_avsc)

            assert isinstance(serializer, AvroSerializer)
            assert client._schema_id_cache["test-value"] == 11
