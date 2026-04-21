# Local stack

Runs everything needed for dev. No cloud, no secrets, no cost.

## What runs and why

| Service | Port | Why |
|---|---|---|
| Redpanda | 19092 | Kafka-compatible event bus. Single broker, no ZooKeeper. |
| Redpanda Console | 8080 | UI for inspecting topics, consumer groups, schema registry. |
| Schema Registry | 18081 | Avro schemas for pitches, game state, corrections. |
| MinIO | 9000 / 9001 | S3-compatible object storage for the lakehouse. Console on 9001. |
| Iceberg REST Catalog | 8181 | Stateless catalog for Iceberg tables. |
| Flink JobManager | 8082 | Web UI and job submission. |
| Flink TaskManager | — | Executes the streaming jobs. |
| Prometheus | 9090 | Metrics scraping. |
| Grafana | 3000 | Dashboards. Anonymous access enabled for local use. |

## Bring it up

From the repo root:

```bash
make up
make ps        # confirm everything healthy
```

First boot pulls several GB of images. Subsequent starts are fast.

## Tear it down

```bash
make down             # stop containers, keep volumes
cd infra/docker && docker compose down -v   # nuke volumes too
```

## Notes

- The Flink checkpoint dir is a shared Docker volume between JobManager and TaskManager. In Phase 4 this moves to S3/MinIO.
- Iceberg REST catalog uses MinIO as the warehouse backend. Two buckets are created at startup: `bullpen-lakehouse` and `bullpen-warehouse`.
- Flink UI is exposed on **8082** (not 8081) to avoid collision with the Redpanda schema registry.
- Grafana credentials: `admin` / `admin`. Not wired to Prometheus yet; that happens in Phase 4.
