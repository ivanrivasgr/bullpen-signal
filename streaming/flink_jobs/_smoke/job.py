"""Phase 1 Day 3 smoke job: read pitches.raw with watermarks and keyed distribution.

Uses the Table API with Flink's avro-confluent format so Confluent-framed
Avro decoding happens in Java. The source defines event-time watermarks, runs
with default Table/SQL parallelism=2, and adds a keyed 1-minute count branch
grouped by (game_pk, pitcher_id).

The raw print sink remains for integration-test visibility:
  [smoke_job]... +I[605400, 1720123200000]
"""

from __future__ import annotations

KAFKA_BOOTSTRAP = "redpanda:29092"
SCHEMA_REGISTRY = "http://redpanda:18081"
SMOKE_GROUP_ID = "bullpen-smoke-job"
SMOKE_PARALLELISM = 2
WATERMARK_DELAY_MINUTES = 5
WINDOW_SIZE_MINUTES = 1


def build_table_config_options(*, parallelism: int = SMOKE_PARALLELISM) -> dict[str, str]:
    """Table/SQL config applied before DDL/DML is registered."""
    return {
        "table.exec.resource.default-parallelism": str(parallelism),
    }


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
            game_pk BIGINT,
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
    """Build the print sink used by the integration test."""
    return """
        CREATE TABLE smoke_sink (
            pitcher_id BIGINT,
            event_time BIGINT
        ) WITH (
            'connector' = 'print',
            'print-identifier' = '[smoke_job]'
        )
    """


def build_smoke_counts_sink_ddl() -> str:
    """Build the keyed count sink used to prove partition-aware aggregation."""
    return """
        CREATE TABLE smoke_counts_sink (
            game_pk BIGINT,
            pitcher_id BIGINT,
            window_start TIMESTAMP(3),
            window_end TIMESTAMP(3),
            pitch_count BIGINT
        ) WITH (
            'connector' = 'print',
            'print-identifier' = '[smoke_counts]'
        )
    """


def build_smoke_insert_sql() -> str:
    """Project decoded pitch rows into the raw print sink."""
    return """
        INSERT INTO smoke_sink
        SELECT pitcher_id, event_time
        FROM pitches_source
    """


def build_smoke_counts_insert_sql(*, window_size_minutes: int = WINDOW_SIZE_MINUTES) -> str:
    """Count pitches per (game_pk, pitcher_id) in 1-minute event-time windows.

    The GROUP BY on (game_pk, pitcher_id, window_start, window_end) creates the
    keyed exchange we want to verify before the production fatigue job.
    """
    return f"""
        INSERT INTO smoke_counts_sink
        SELECT
            game_pk,
            pitcher_id,
            window_start,
            window_end,
            COUNT(*) AS pitch_count
        FROM TABLE(
            TUMBLE(
                TABLE pitches_source,
                DESCRIPTOR(event_ts),
                INTERVAL '{window_size_minutes}' MINUTE
            )
        )
        GROUP BY game_pk, pitcher_id, window_start, window_end
    """


def main() -> None:
    from pyflink.table import EnvironmentSettings, TableEnvironment

    settings = EnvironmentSettings.in_streaming_mode()
    t_env = TableEnvironment.create(settings)

    for key, value in build_table_config_options().items():
        t_env.get_config().set(key, value)

    t_env.execute_sql(build_pitches_source_ddl())
    t_env.execute_sql(build_smoke_sink_ddl())
    t_env.execute_sql(build_smoke_counts_sink_ddl())

    statement_set = t_env.create_statement_set()
    statement_set.add_insert_sql(build_smoke_insert_sql())
    statement_set.add_insert_sql(build_smoke_counts_insert_sql())
    statement_set.execute()


if __name__ == "__main__":
    main()
