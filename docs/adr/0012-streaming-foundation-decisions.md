# ADR 0012 - Streaming Foundation Decisions

## Status

Accepted - 2026-05-01

## Context

Phase 1 forced several foundation decisions that will be expensive to change
once downstream jobs, lakehouse tables, and dashboard consumers depend on them:

1. Kafka value encoding
2. Schema registration and compatibility checks
3. Flink runtime and connector dependency management
4. How Iceberg bronze writes are bootstrapped locally

These decisions are coupled. Avro affects Flink deserialization. Flink
connector versions affect Iceberg write support. Iceberg's S3FileIO affects
which runtime JARs need to exist in the Flink JVM classpath.

## Decisions

### Wire Format: Avro Values With Confluent Framing

Kafka values use Avro with Confluent Schema Registry framing. Keys remain plain
UTF-8 strings.

Avro is not as easy to inspect as JSON, but it gives the project a real schema
contract, compact payloads, and native integration with Flink's Table API.

### Schema Registry: Redpanda's Confluent-Compatible Registry

The local stack uses Redpanda's Schema Registry endpoint. Producers register
schemas before publishing, and integration tests rely on schema-aware
deserialization rather than treating Kafka values as opaque bytes.

This keeps local development close to the Confluent protocol without adding a
separate registry service.

### Flink Runtime: PyFlink 1.20 On A Custom Local Image

The local smoke job uses PyFlink/Table API against the Dockerized Flink 1.20
runtime. Python owns the job definition, but Avro decoding, Kafka consumption,
windowing, and Iceberg writes happen in Flink's JVM runtime.

The first implementation attempt tried to decode Confluent Avro in Python from
a DataStream source. That path was rejected because PyFlink's exposed
DataStream deserializers were a poor fit for binary Avro payloads. The Table
API with avro-confluent is the stable path.

### Connector JARs: Explicit, Pinned, Copied Into /opt/flink/lib

Flink connector JARs are downloaded through
infra/docker/flink-libs/download.sh and mounted into the containers. A startup
wrapper copies them into /opt/flink/lib before the JVM starts because Flink
scans that directory for the runtime classpath.

The Iceberg sink requires more than iceberg-flink-runtime. Local S3 writes also
need Hadoop client classes and iceberg-aws-bundle so S3FileIO can create files
in MinIO.

### Bronze Tables: Schema-As-Code Plus Idempotent Creation Script

bronze.pitches is defined in lakehouse/schemas/bronze_pitches.py and created
through infra/scripts/create_bronze_tables.py. Flink writes append-only bronze
data; deduplication and business corrections belong in silver.

## Consequences

### Positive

- Kafka payloads have real schema contracts.
- Flink jobs can decode Confluent Avro without custom Python byte parsing.
- The first durable Kafka -> Flink -> Iceberg path is locally reproducible.
- DuckDB can inspect Iceberg metadata and data without a separate analytics
  service.

### Negative

- Local Flink classpath management is explicit and somewhat verbose.
- Avro enum fields were converted to strings because Flink 1.20's
  avro-confluent Table API did not resolve enum symbols cleanly into SQL STRING
  columns.
- Schema Registry subjects may need local deletion during pre-production schema
  breaks. This is acceptable before public compatibility guarantees exist.
- Iceberg writes require checkpoint behavior, so integration tests are slower
  than pure Kafka smoke tests.

## Alternatives Considered

### JSON Values

Rejected. JSON is easier to inspect manually but pushes validation to runtime
and weakens the schema contract.

### Python-Side Avro Decoding In PyFlink DataStream Jobs

Rejected after implementation. The exposed PyFlink DataStream path did not
provide a clean binary Confluent Avro deserializer. Table API decoding in Java
is simpler and closer to the production shape.

### Hiding Connector JARs In The Image Only

Rejected for now. The explicit download script makes dependency changes visible
in diffs and keeps the local stack debuggable during Phase 1.

## Follow-Up

- Phase 2 should decide how matchup uncertainty is represented.
- Phase 3 should decide reconciliation taxonomy and governance monitoring.
- Once schemas stabilize, compatibility policy should move from informal local
  deletion to documented Schema Registry compatibility rules.
