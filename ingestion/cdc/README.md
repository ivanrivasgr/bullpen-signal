# CDC source (Phase 2+)

This directory is reserved for the Debezium-style CDC feed that captures
official MLB scoring corrections and pushes them to `corrections.cdc`.

For Phase 0–1, corrections are synthesized by the replay engine's noise
injector. Phase 2 replaces that with a real CDC source watching a Postgres
table populated from StatsAPI polling.

Not implemented yet.
