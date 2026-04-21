# ADR 0002 — Redpanda for the event bus

- **Status:** Accepted
- **Date:** Phase 0

## Context

Need a Kafka-compatible event bus that runs cleanly on a laptop for dev and
in a managed service for the public demo.

## Decision

Redpanda in Docker for local. Confluent Cloud or Redpanda Cloud free tier
for the demo deploy in Phase 4.

## Alternatives considered

- **Apache Kafka + ZooKeeper.** Heavier for local dev. KRaft mode is an
  option but adds operational steps we do not need at Phase 0.
- **Kafka via Strimzi on k3s.** Overkill. If the project grew beyond a
  single node demo this would be revisited.
- **NATS JetStream.** Lighter, but loses Kafka-native tooling (kcat, Flink
  connectors, dbt-kafka adapters) that the rest of the stack expects.

## Consequences

- The rest of the stack treats the bus as Kafka-protocol. Any Redpanda
  specifics (for example, the built-in schema registry) get an abstraction.
- Single-broker dev means no replication; the local stack is not
  fault-tolerant, which is fine for the intended use.
