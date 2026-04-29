"""Phase 1 Day 2 smoke job: read pitches.raw via Table API + Confluent Avro format.

This is the wire-up smoke test. It uses the Table API with the built-in
`avro-confluent` format which natively understands the Confluent Schema Registry
wire format (magic byte + schema_id + Avro payload). No Python operators are
involved on the data path; deserialization happens in Java.

The job creates a source table over pitches.raw, then INSERTs into a print
sink which writes each row to TaskManager stdout in `+I[col1, col2, ...]` form.
That output is what the integration test asserts on.

Why Table API instead of DataStream + custom decode:
  PyFlink's SimpleStringSchema is the only DataStream value deserializer
  exposed in the Python API, and it irreversibly corrupts non-UTF-8 bytes
  via Java's `replace` errors handling — incompatible with binary Avro
  payloads. The Table API + avro-confluent format avoids the issue
  entirely by doing the decode in Java with full SR integration.

Run with:
  bash streaming/flink_jobs/_smoke/submit.sh

Output appears in the TaskManager stdout, one line per pitch, e.g.:
  +I[605400, 1720123200000]
"""

from __future__ import annotations

from pyflink.table import EnvironmentSettings, TableEnvironment

# Inside the container these resolve to the docker-compose service names.
KAFKA_BOOTSTRAP = "redpanda:29092"
SCHEMA_REGISTRY = "http://redpanda:18081"


def main() -> None:
    settings = EnvironmentSettings.in_streaming_mode()
    t_env = TableEnvironment.create(settings)

    # Source table: pitches.raw with Confluent-framed Avro values.
    # Only the two fields the smoke test cares about are projected;
    # other Avro fields are silently ignored by the deserializer.
    t_env.execute_sql(f"""
        CREATE TABLE pitches_source (
            pitcher_id BIGINT,
            event_time BIGINT
        ) WITH (
            'connector' = 'kafka',
            'topic' = 'pitches.raw',
            'properties.bootstrap.servers' = '{KAFKA_BOOTSTRAP}',
            'properties.group.id' = 'bullpen-smoke-job',
            'scan.startup.mode' = 'earliest-offset',
            'value.format' = 'avro-confluent',
            'value.avro-confluent.url' = '{SCHEMA_REGISTRY}'
        )
    """)

    # Sink: built-in print connector. Each row is rendered as
    # `+I[<pitcher_id>, <event_time>]` to TaskManager stdout.
    t_env.execute_sql("""
        CREATE TABLE smoke_sink (
            pitcher_id BIGINT,
            event_time BIGINT
        ) WITH (
            'connector' = 'print',
            'print-identifier' = '[smoke_job]'
        )
    """)

    # The job itself: pull both fields straight through. The print sink will
    # emit one line per pitch with the [smoke_job] tag the integration test
    # greps for.
    t_env.execute_sql("""
        INSERT INTO smoke_sink
        SELECT pitcher_id, event_time FROM pitches_source
    """)


if __name__ == "__main__":
    main()
