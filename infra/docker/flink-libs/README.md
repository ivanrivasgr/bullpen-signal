# Flink connector JARs

This directory holds connector JARs that get mounted into the Flink jobmanager
and taskmanager containers at `/opt/flink/lib/connectors/`. Flink picks them
up at startup; restarting the containers is required after adding or
removing JARs.

## Why this directory exists

The base `flink:2.2.0-scala_2.12-java11` image ships only the core JARs
(`flink-dist`, `flink-cep`, `flink-csv`, `flink-json`, `flink-table-*`,
`flink-scala`). Connectors for Kafka, Avro, and Iceberg are downloaded
separately and live here so they can be version-controlled (URLs in this
README) without bloating the docker image.

## Required JARs (Phase 1 Day 2)

All JARs are downloaded from Maven Central. URLs are pinned to specific
versions for reproducibility. Bump versions only with a corresponding ADR
update.

### 1. Kafka source/sink

- Artifact: `flink-connector-kafka`
- Version: **3.4.0-1.20** (compatible with Flink 1.20.x; expected to work
  with 2.2.0 — verify at smoke test time, fall back to 3.3.0-1.20 if
  the 1.20-line API broke in 2.2.0)
- URL:
  https://repo.maven.apache.org/maven2/org/apache/flink/flink-connector-kafka/3.4.0-1.20/flink-connector-kafka-3.4.0-1.20.jar
- Filename: `flink-connector-kafka-3.4.0-1.20.jar`

### 2. Kafka SQL connector (optional, kept for future Table API work)

- Artifact: `flink-sql-connector-kafka`
- Version: **3.4.0-1.20**
- URL:
  https://repo.maven.apache.org/maven2/org/apache/flink/flink-sql-connector-kafka/3.4.0-1.20/flink-sql-connector-kafka-3.4.0-1.20.jar
- Filename: `flink-sql-connector-kafka-3.4.0-1.20.jar`

### 3. Avro core

- Artifact: `flink-avro`
- Version: **1.20.0**
- URL:
  https://repo.maven.apache.org/maven2/org/apache/flink/flink-avro/1.20.0/flink-avro-1.20.0.jar
- Filename: `flink-avro-1.20.0.jar`

### 4. Avro + Confluent Schema Registry integration

- Artifact: `flink-avro-confluent-registry`
- Version: **1.20.0**
- URL:
  https://repo.maven.apache.org/maven2/org/apache/flink/flink-avro-confluent-registry/1.20.0/flink-avro-confluent-registry-1.20.0.jar
- Filename: `flink-avro-confluent-registry-1.20.0.jar`

### 5. Iceberg runtime (used in Day 4)

- Artifact: `iceberg-flink-runtime-1.20`
- Version: **1.10.1**
- URL:
  https://repo.maven.apache.org/maven2/org/apache/iceberg/iceberg-flink-runtime-1.20/1.10.1/iceberg-flink-runtime-1.20-1.10.1.jar
- Filename: `iceberg-flink-runtime-1.20-1.10.1.jar`

## Download script

Run from the repo root:

```bash
bash infra/docker/flink-libs/download.sh
```

The script is idempotent: re-running skips already-downloaded JARs.

## Verifying

After mounting and restarting Flink, verify JARs are visible inside
the container:

```bash
docker exec bullpen-flink-jm ls /opt/flink/lib/connectors/
```

All five JARs should be listed.

## Compatibility note

If `flink-connector-kafka-3.4.0-1.20` fails to load against Flink 2.2.0
(symptoms: `NoClassDefFoundError`, `IncompatibleClassChangeError`,
`UnsupportedOperationException` from a connector class at job submission),
the fallback path is:

1. Replace with `3.3.0-1.20`
2. If that also fails, document the gap and use the legacy
   `flink-connector-kafka_2.12` 3.x line which is Scala-versioned and
   tracks Flink 1.x more conservatively
3. If that also fails, escalate: this is an ADR moment, not a code fix
