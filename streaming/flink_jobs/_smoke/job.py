"""Phase 1 Day 3 smoke job: read pitches.raw with event-time watermarks.

Uses the Table API with Flink's avro-confluent format so Confluent-framed
Avro decoding happens in Java. The source defines an event-time column and a
5-minute bounded out-of-orderness watermark.

The print sink still emits one row per pitch for integration-test visibility:
  [smoke_job]... +I[605400, 1720123200000]
"""

from __future__ import annotations

KAFKA_BOOTSTRAP = "redpanda:29092"
SCHEMA_REGISTRY = "http://redpanda:18081"
SMOKE_GROUP_ID = "bullpen-smoke-job"
WATERMARK_DELAY_MINUTES = 5


def build_pitches_source_ddl(
    *,
    bootstrap_servers: str = KAFKA_BOOTSTRAP,
    schema_registry_url: str = SCHEMA_REGISTRY,
    group_id: str = SMOKE_GROUP_ID,
    watermark_delay_minutes: int = WATERMARK_DELAY_MINUTES,
) -> str:
    """Build the Kafka source DDL with event-time watermarking."""
    return f"""
        CREATE TABLE pitches_source (
            pitcher_id BIGINT,
            event_time BIGINT,
            event_ts AS TO_TIMESTAMP_LTZ(event_time, 3),
            WATERMARK FOR event_ts AS event_ts - INTERVAL '{watermark_delay_minutes}' MINUTE
        ) WITH (
            'connector' = 'kafka',
            'topic' = 'pitches.raw',
            'properties.bootstrap.servers' = '{bootstrap_servers}',
            'properties.group.id' = '{group_id}',
            'scan.startup.mode' = 'earliest-offset',
            'value.format' = 'avro-confluent',
            'value.avro-confluent.url' = '{schema_registry_url}'
        )
    """


def build_smoke_sink_ddl() -> str:
    """Build the print sink DDL used by the integration test."""
    return """
        CREATE TABLE smoke_sink (
            pitcher_id BIGINT,
            event_time BIGINT
        ) WITH (
            'connector' = 'print',
            'print-identifier' = '[smoke_job]'
        )
    """


def build_smoke_insert_sql() -> str:
    """Project decoded pitch rows into the print sink."""
    return """
        INSERT INTO smoke_sink
        SELECT pitcher_id, event_time
        FROM pitches_source
    """


def main() -> None:
    from pyflink.table import EnvironmentSettings, TableEnvironment

    settings = EnvironmentSettings.in_streaming_mode()
    t_env = TableEnvironment.create(settings)

    t_env.execute_sql(build_pitches_source_ddl())
    t_env.execute_sql(build_smoke_sink_ddl())
    t_env.execute_sql(build_smoke_insert_sql())


if __name__ == "__main__":
    main()
