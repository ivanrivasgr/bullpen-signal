#!/usr/bin/env bash
# Creates Kafka topics for the Bullpen Signal streaming pipeline.
#
# Idempotent: `topic create` returns a non-zero exit code if the topic
# already exists, which is why each line is suffixed with `|| true`.
#
# Partition count rationale: 3 gives us room to parallelize per-pitcher
# state in Flink without overkill for a local dev environment. Production
# would scale this to match expected pitcher concurrency (MLB: ~30 games
# simultaneous x ~15 pitchers per game = ~450 keys active worst case).

set -euo pipefail

RPK="docker exec bullpen-redpanda rpk"
PARTITIONS="${PARTITIONS:-3}"
REPLICAS="${REPLICAS:-1}"

echo "Creating topics (partitions=${PARTITIONS}, replicas=${REPLICAS})..."

# Raw ingestion topics (source of truth from replay engine / live feed)
$RPK topic create pitches.raw       --partitions "$PARTITIONS" --replicas "$REPLICAS" || true
$RPK topic create game_state.raw    --partitions "$PARTITIONS" --replicas "$REPLICAS" || true
$RPK topic create corrections.cdc   --partitions "$PARTITIONS" --replicas "$REPLICAS" || true

# Feature topics (computed by Flink jobs in Milestone 2)
$RPK topic create features.fatigue.v1   --partitions "$PARTITIONS" --replicas "$REPLICAS" || true
$RPK topic create features.leverage.v1  --partitions "$PARTITIONS" --replicas "$REPLICAS" || true
$RPK topic create features.matchup.v1   --partitions "$PARTITIONS" --replicas "$REPLICAS" || true

# Alert topic (emitted by orchestrator)
$RPK topic create alerts.v1 --partitions "$PARTITIONS" --replicas "$REPLICAS" || true

echo ""
echo "Topics created. Listing current state:"
$RPK topic list
