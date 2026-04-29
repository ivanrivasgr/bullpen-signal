#!/usr/bin/env bash
# Submit the smoke job to the local Flink cluster.
#
# Usage: bash streaming/flink_jobs/_smoke/submit.sh
#
# The script copies job.py into the jobmanager container, then runs flink
# run -py against it. Output goes to the TaskManager stdout; tail it with:
#   docker logs -f bullpen-flink-tm

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
JOB_PY="${REPO_ROOT}/streaming/flink_jobs/_smoke/job.py"

if [[ ! -f "$JOB_PY" ]]; then
    echo "ERROR: ${JOB_PY} not found"
    exit 1
fi

CONTAINER_PATH="/tmp/smoke_job.py"
echo "[submit.sh] copying job to bullpen-flink-jm:${CONTAINER_PATH}"
docker cp "$JOB_PY" "bullpen-flink-jm:${CONTAINER_PATH}"

echo "[submit.sh] submitting via flink run -py"
docker exec bullpen-flink-jm /opt/flink/bin/flink run \
    -py "$CONTAINER_PATH" \
    --detached

echo ""
echo "[submit.sh] submitted. Watch output with:"
echo "  docker logs -f bullpen-flink-tm"
echo ""
echo "[submit.sh] cancel the job with:"
echo "  docker exec bullpen-flink-jm /opt/flink/bin/flink list"
echo "  docker exec bullpen-flink-jm /opt/flink/bin/flink cancel <jobId>"
