# Milestone 1 - Replay to Bronze

```mermaid
sequenceDiagram
    autonumber
    participant Replay as Replay Engine
    participant Kafka as Redpanda Kafka
    participant Registry as Schema Registry
    participant Flink as PyFlink Smoke Job
    participant Catalog as Iceberg REST Catalog
    participant MinIO as MinIO Warehouse
    participant DuckDB as Local DuckDB Helper

    Replay->>Registry: Register Avro subjects
    Replay->>Kafka: Publish Confluent-framed pitch events
    Flink->>Registry: Resolve Avro schema
    Flink->>Kafka: Read pitches.raw with event-time watermark
    Flink-->>Flink: Emit smoke print rows and keyed counts
    Flink->>Catalog: Resolve bullpen.bronze.pitches
    Flink->>MinIO: Write Iceberg data and metadata files
    Catalog->>MinIO: Track latest table metadata
    DuckDB->>Catalog: Resolve table metadata location
    DuckDB->>MinIO: Read snapshot through PyIceberg Arrow materialization

```

## Demo Checklist

- Start the local stack.
- Ensure `bronze.pitches` exists.
- Run the bronze Iceberg integration test.
- Show `[smoke_job]` lines for published pitcher IDs.
- Query `bronze_pitches` locally through `lakehouse.query`.
- Show the Iceberg metadata location changed after commit.
