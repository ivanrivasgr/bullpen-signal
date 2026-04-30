"""Phase 1 Day 4 smoke job: Kafka Avro -> Flink -> print sinks + Iceberg bronze."""

from __future__ import annotations

KAFKA_BOOTSTRAP = "redpanda:29092"
SCHEMA_REGISTRY = "http://redpanda:18081"
SMOKE_GROUP_ID = "bullpen-smoke-job"
SMOKE_PARALLELISM = 2
WATERMARK_DELAY_MINUTES = 5
WINDOW_SIZE_MINUTES = 1

ICEBERG_CATALOG = "bullpen"
ICEBERG_REST_URI = "http://iceberg-rest:8181"
ICEBERG_WAREHOUSE = "s3://bullpen-warehouse/"
S3_ENDPOINT = "http://minio:9000"
S3_ACCESS_KEY = "minioadmin"
S3_SECRET_KEY = "minioadmin"
AWS_REGION = "us-east-1"


def build_table_config_options(parallelism: int = SMOKE_PARALLELISM) -> dict[str, str]:
    return {"table.exec.resource.default-parallelism": str(parallelism)}


def build_iceberg_catalog_ddl() -> str:
    return f"""
        CREATE CATALOG {ICEBERG_CATALOG} WITH (
            'type' = 'iceberg',
            'catalog-type' = 'rest',
            'uri' = '{ICEBERG_REST_URI}',
            'warehouse' = '{ICEBERG_WAREHOUSE}',
            'io-impl' = 'org.apache.iceberg.aws.s3.S3FileIO',
            's3.endpoint' = '{S3_ENDPOINT}',
            's3.path-style-access' = 'true',
            's3.access-key-id' = '{S3_ACCESS_KEY}',
            's3.secret-access-key' = '{S3_SECRET_KEY}',
            'client.region' = '{AWS_REGION}'
        )
    """


def build_pitches_source_ddl(
    *,
    bootstrap_servers: str = KAFKA_BOOTSTRAP,
    schema_registry_url: str = SCHEMA_REGISTRY,
    group_id: str = SMOKE_GROUP_ID,
    watermark_delay_minutes: int = WATERMARK_DELAY_MINUTES,
) -> str:
    return f"""
        CREATE TABLE pitches_source (
            event_time BIGINT NOT NULL,
            ingest_time BIGINT NOT NULL,
            game_pk BIGINT NOT NULL,
            at_bat_number INT NOT NULL,
            pitch_number INT NOT NULL,
            inning INT NOT NULL,
            inning_topbot STRING NOT NULL,
            pitcher_id BIGINT NOT NULL,
            batter_id BIGINT NOT NULL,
            pitch_type STRING,
            release_speed DOUBLE,
            release_spin_rate DOUBLE,
            plate_x DOUBLE,
            plate_z DOUBLE,
            zone INT,
            balls INT NOT NULL,
            strikes INT NOT NULL,
            outs_when_up INT NOT NULL,
            on_1b BIGINT,
            on_2b BIGINT,
            on_3b BIGINT,
            description STRING,
            events STRING,
            home_score INT NOT NULL,
            away_score INT NOT NULL,
            is_late_arrival BOOLEAN NOT NULL,
            is_duplicate BOOLEAN NOT NULL,
            correction_of STRING,
            kafka_partition INT METADATA FROM 'partition' VIRTUAL,
            source_offset BIGINT METADATA FROM 'offset' VIRTUAL,
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
    return """
        CREATE TABLE smoke_sink (
            pitcher_id BIGINT NOT NULL,
            event_time BIGINT
        ) WITH (
            'connector' = 'print',
            'print-identifier' = '[smoke_job]'
        )
    """


def build_smoke_counts_sink_ddl() -> str:
    return """
        CREATE TABLE smoke_counts_sink (
            game_pk BIGINT NOT NULL,
            pitcher_id BIGINT NOT NULL,
            window_start TIMESTAMP(3),
            window_end TIMESTAMP(3),
            pitch_count BIGINT
        ) WITH (
            'connector' = 'print',
            'print-identifier' = '[smoke_counts]'
        )
    """


def build_smoke_insert_sql() -> str:
    return """
        INSERT INTO smoke_sink
        SELECT pitcher_id, event_time
        FROM pitches_source
    """


def build_smoke_counts_insert_sql(
    window_size_minutes: int = WINDOW_SIZE_MINUTES,
) -> str:
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


def build_bronze_pitches_insert_sql() -> str:
    return f"""
        INSERT INTO {ICEBERG_CATALOG}.bronze.pitches
        SELECT
            TO_TIMESTAMP_LTZ(event_time, 3) AS event_time,
            game_pk,
            at_bat_number,
            pitch_number,
            inning,
            inning_topbot,
            pitcher_id,
            batter_id,
            pitch_type,
            release_speed,
            release_spin_rate,
            plate_x,
            plate_z,
            zone,
            balls,
            strikes,
            outs_when_up,
            on_1b,
            on_2b,
            on_3b,
            description,
            events,
            home_score,
            away_score,
            is_late_arrival,
            is_duplicate,
            correction_of,
            CURRENT_TIMESTAMP AS ingestion_time,
            source_offset AS source_offset,
            kafka_partition AS kafka_partition
        FROM pitches_source
    """


def main() -> None:
    from pyflink.table import EnvironmentSettings, TableEnvironment

    settings = EnvironmentSettings.in_streaming_mode()
    t_env = TableEnvironment.create(settings)

    for key, value in build_table_config_options().items():
        t_env.get_config().set(key, value)

    t_env.execute_sql(build_iceberg_catalog_ddl())
    t_env.execute_sql(build_pitches_source_ddl())
    t_env.execute_sql(build_smoke_sink_ddl())
    t_env.execute_sql(build_smoke_counts_sink_ddl())

    statement_set = t_env.create_statement_set()
    statement_set.add_insert_sql(build_smoke_insert_sql())
    statement_set.add_insert_sql(build_smoke_counts_insert_sql())
    statement_set.add_insert_sql(build_bronze_pitches_insert_sql())
    statement_set.execute()


if __name__ == "__main__":
    main()
