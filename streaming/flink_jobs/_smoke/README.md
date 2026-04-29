# Smoke job

A throwaway PyFlink job that proves the Phase 1 wiring works end-to-end:

  Replay engine -> pitches.raw (Avro+SR) -> Flink KafkaSource -> decode -> print

The point of this job is **not** the analytics. It is to confirm that:

1. The custom `bullpen-flink:2.2.0-pyflink` image runs PyFlink correctly.
2. The connector JARs mounted at `/opt/flink/lib/connectors/` resolve and
   `KafkaSource.builder()` instantiates without `NoClassDefFoundError`.
3. Confluent-framed Avro messages can be decoded inside a Flink operator
   using the project's SchemaRegistryClient wrapper + fastavro.
4. The JM and TM communicate, accept jobs, and print to TM stdout.

The production jobs (`fatigue/`, `leverage/`, `matchup/`,
`alert_orchestrator/`) reuse the decode pattern from this smoke job.

## Running

```bash
# 1. Make sure the stack is up and the replay engine is publishing.
make ps    # 8 containers Up
# In another terminal, after this job is running:
python -m ingestion.replay_engine.run --speed 100

# 2. Submit the smoke job.
bash streaming/flink_jobs/_smoke/submit.sh

# 3. Watch the TaskManager stdout.
docker logs -f bullpen-flink-tm
```

You should see lines like:
[smoke_job] pitcher=605400 event_time_ms=1720121400000
[smoke_job] pitcher=605400 event_time_ms=1720121401234
[smoke_job] pitcher=519242 event_time_ms=1720121402100

## Cancelling

```bash
docker exec bullpen-flink-jm /opt/flink/bin/flink list
docker exec bullpen-flink-jm /opt/flink/bin/flink cancel <jobId>
```

## Why no test for this job

PyFlink jobs are difficult to unit-test. The wiring is verified visually
and by the integration test in Tarea 4 (next commit) which submits the
job, runs the replay engine, and asserts on TaskManager stdout content.
