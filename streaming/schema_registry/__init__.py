"""Schema Registry integration for the bullpen-signal streaming layer."""

from streaming.schema_registry.client import (
    BullpenSchemaError,
    SchemaRegistryClient,
)

__all__ = ["BullpenSchemaError", "SchemaRegistryClient"]
