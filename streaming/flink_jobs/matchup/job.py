"""Streaming matchup signal job: pitches.raw -> matchup signals -> Iceberg.

Reads the pitch stream from Kafka (Avro via the schema registry), derives
each pitch's handedness matchup, expands it into one or two signal rows
(ADR 0020), and writes them to the streaming.matchup_signals Iceberg
table (ADR 0022). This is the streaming half of the dual-path comparison
ADR 0001 named as the product: the same signal the batch dbt model
produces, computed in real time from the same shared core, so the
reconciliation compares a real-time decision against the batch truth.

Point-in-time honesty (ADR 0021) is a property of the input, not job
state: each pitch carries the lineup_state it was seen under and, when
uncertain, the projected batter the system inferred at that moment. The
job is stateless and row-wise — it never looks across pitches — so it
cannot peek at information that arrived later. The handedness seed it
joins is static (a player's hand does not change), so resolving it is
not a peek either.

Two functions carry the logic, both shared with the batch path so the
two cannot drift:
- derive_handedness (scalar UDF): pitch player IDs -> handedness matchup
- emit_signals (table UDTF): matchup + lineup_state -> one or two signal
  rows, via plan_signal_emissions + compute_signal_fields

The handedness UDF is scalar (returns a ROW, accessed by field); only the
emission UDTF is a table function joined with LATERAL TABLE.
"""

from __future__ import annotations

KAFKA_BOOTSTRAP = "redpanda:29092"
SCHEMA_REGISTRY = "http://redpanda:18081"
MATCHUP_GROUP_ID = "bullpen-matchup-signal-job"
MATCHUP_PARALLELISM = 2
WATERMARK_DELAY_MINUTES = 5
CHECKPOINT_INTERVAL_MS = 5000

ICEBERG_CATALOG = "bullpen"
ICEBERG_REST_URI = "http://iceberg-rest:8181"
ICEBERG_WAREHOUSE = "s3://bullpen-warehouse/"
S3_ENDPOINT = "http://minio:9000"
S3_ACCESS_KEY = "minioadmin"
S3_SECRET_KEY = "minioadmin"
AWS_REGION = "us-east-1"

SINK_IDENTIFIER = f"{ICEBERG_CATALOG}.streaming.matchup_signals"


def build_table_config_options(
    parallelism: int = MATCHUP_PARALLELISM,
    checkpoint_interval_ms: int = CHECKPOINT_INTERVAL_MS,
) -> dict[str, str]:
    # The Iceberg sink commits its data files on checkpoint, so checkpointing
    # must be enabled for the job to materialize any rows. A short interval
    # keeps the streaming write latency low and ensures the bounded backlog
    # (replay) commits promptly rather than waiting on the cluster default.
    return {
        "table.exec.resource.default-parallelism": str(parallelism),
        "execution.checkpointing.interval": f"{checkpoint_interval_ms} ms",
    }


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
    group_id: str = MATCHUP_GROUP_ID,
    watermark_delay_minutes: int = WATERMARK_DELAY_MINUTES,
) -> str:
    # Own source DDL rather than importing the Phase 1 smoke job's, so this
    # production job does not depend on the smoke. has_projection is derived
    # here from projected_batter_id so the emission UDTF gets a clean boolean.
    return f"""
        CREATE TABLE pitches_source (
            event_time BIGINT NOT NULL,
            game_pk BIGINT NOT NULL,
            at_bat_number INT NOT NULL,
            pitch_number INT NOT NULL,
            pitcher_id BIGINT NOT NULL,
            batter_id BIGINT NOT NULL,
            projected_batter_id BIGINT,
            lineup_state STRING,
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


def build_handedness_view_ddl() -> str:
    # The handedness UDF is scalar and returns a ROW; access its fields.
    # lineup_state defaults to 'confirmed' when the source omits it, matching
    # the batch treatment of a pitch with no recorded uncertainty.
    return """
        CREATE TEMPORARY VIEW pitches_with_handedness AS
        SELECT
            event_time,
            event_ts,
            game_pk,
            at_bat_number,
            pitch_number,
            pitcher_id,
            batter_id,
            COALESCE(lineup_state, 'confirmed') AS lineup_state,
            projected_batter_id IS NOT NULL AS has_projection,
            derive_handedness(pitcher_id, batter_id, projected_batter_id).handedness_matchup
                AS handedness_matchup,
            derive_handedness(pitcher_id, batter_id, projected_batter_id).projected_handedness_matchup
                AS projected_handedness_matchup
        FROM pitches_source
    """


def build_matchup_signals_insert_sql() -> str:
    # The emission UDTF expands each pitch into one or two signal rows.
    # The natural key and identity columns travel from the pitch; the signal
    # columns come from the UDTF. handedness_matchup is the real matchup, kept
    # as the batch path keeps it for reconciliation grouping (ADR 0022).
    return f"""
        INSERT INTO {SINK_IDENTIFIER}
        SELECT
            CAST(p.event_ts AS TIMESTAMP_LTZ(6)) AS event_time,
            p.game_pk,
            p.at_bat_number,
            p.pitch_number,
            p.pitcher_id,
            p.batter_id,
            p.handedness_matchup,
            CAST(e.signal_value AS DOUBLE) AS signal_value,
            e.confidence_band,
            e.lineup_state_at_emission
        FROM pitches_with_handedness AS p,
        LATERAL TABLE(emit_signals(
            p.lineup_state,
            p.handedness_matchup,
            p.projected_handedness_matchup,
            p.has_projection
        )) AS e(signal_value, confidence_band, lineup_state_at_emission)
    """


def main() -> None:
    from pyflink.table import EnvironmentSettings, TableEnvironment

    from streaming.flink_jobs.matchup.emission_udtf import build_emission_udtf
    from streaming.flink_jobs.matchup.handedness_udf import build_handedness_udf

    settings = EnvironmentSettings.in_streaming_mode()
    t_env = TableEnvironment.create(settings)

    for key, value in build_table_config_options().items():
        t_env.get_config().set(key, value)

    t_env.create_temporary_function("derive_handedness", build_handedness_udf())
    t_env.create_temporary_function("emit_signals", build_emission_udtf())

    t_env.execute_sql(build_iceberg_catalog_ddl())
    t_env.execute_sql(build_pitches_source_ddl())
    t_env.execute_sql(build_handedness_view_ddl())

    statement_set = t_env.create_statement_set()
    statement_set.add_insert_sql(build_matchup_signals_insert_sql())
    # execute() submits the job asynchronously and returns a TableResult.
    # Without waiting, this process would exit immediately and tear down the
    # job before it runs. wait() blocks on the job; for the unbounded Kafka
    # source it blocks until the job is stopped (e.g. cancelled or the
    # process is signalled), by which point the Iceberg sink has committed
    # on checkpoint.
    statement_set.execute().wait()


if __name__ == "__main__":
    main()
