# LinkedIn Post 2 Draft - Milestone 1

Today I finished the first durable streaming slice of Bullpen Signal.

The project can now replay synthetic pitch events into Kafka, decode Avro in
Flink, apply event-time watermarks, keep smoke-test print sinks for direct
runtime visibility, and write decoded pitch rows into a local Iceberg bronze
table backed by MinIO.

The most useful part was not that everything worked immediately. It did not.

The path exposed the real integration edges:

- Flink needed the right Kafka, Avro, Hadoop, Iceberg, and AWS bundle jars.
- Avro enum modeling had to be adjusted so Flink SQL could deserialize the
  schema consistently.
- Iceberg S3FileIO needed an explicit local AWS region.
- DuckDB native Iceberg reads hit a local metadata compatibility issue, so
  PyIceberg now owns snapshot reads and DuckDB owns SQL over Arrow tables.
- The bronze schema needed one final cleanup before announcement: event-time
  partitioning, no duplicate ingest timestamp, and auditable Kafka partition
  plus offset provenance.

That is exactly why I wanted this milestone early. The goal was not a polished
dashboard yet. The goal was to prove the hardest plumbing: Kafka -> Flink ->
Iceberg, with tests that catch the integration failures instead of assuming the
architecture works on paper.

Next up: documenting the architecture decisions, then moving toward the silver
layer and baseball feature computation.
