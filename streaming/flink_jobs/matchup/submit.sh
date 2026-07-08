#!/usr/bin/env bash
# Submit the matchup signal job to the local Flink cluster.
#
# Usage: bash streaming/flink_jobs/matchup/submit.sh
#
# The job reads pitches.raw and writes streaming.matchup_signals. Unlike the
# smoke job, it imports repo modules (signals.matchup_core, the handedness UDF,
# the emission UDTF) AND reads the handedness seed CSV at runtime. The
# jobmanager and taskmanager are SEPARATE containers, so both the Python import
# surface and the seed file must reach the workers -- otherwise the taskmanager
# raises ModuleNotFoundError (missing modules) or FileNotFoundError (missing
# seed). Flink's --pyFiles ships the staged directory to every worker, which is
# the mechanism that scales past one TM.
#
# The script stages the import surface plus the seed into a single directory
# inside the jobmanager, hands it to flink run via --pyFiles, and names the
# entrypoint via --python. It is idempotent: it cancels any RUNNING matchup job
# first (one Iceberg-sink writer at a time) and re-copies the current code, so a
# code change (e.g. a core fix) actually reaches the workers on the next run.
#
# Watch output:  docker logs -f bullpen-flink-tm
# List / cancel: docker exec bullpen-flink-jm /opt/flink/bin/flink list
#                docker exec bullpen-flink-jm /opt/flink/bin/flink cancel <jobId>

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
JM="bullpen-flink-jm"
STAGE="/tmp/bullpen"
ENTRYPOINT="${STAGE}/streaming/flink_jobs/matchup/job.py"

# The runtime surface the job needs, staged to mirror the repo layout so both
# the package imports (signals.*, streaming.flink_jobs.matchup.*) and the seed
# path (dbt/seeds/...) resolve once --pyFiles puts this directory on each
# worker. The handedness UDF reads player_handedness.csv at runtime, so the
# seed ships alongside the code.
PATHS=(
    "signals/__init__.py"
    "signals/matchup_core.py"
    "signals/matchup_signal.py"
    "signals/matchup_calibration.py"
    "signals/handedness_lookup.py"
    "streaming/__init__.py"
    "streaming/flink_jobs/__init__.py"
    "streaming/flink_jobs/matchup/__init__.py"
    "streaming/flink_jobs/matchup/job.py"
    "streaming/flink_jobs/matchup/handedness_udf.py"
    "streaming/flink_jobs/matchup/matchup_udf.py"
    "streaming/flink_jobs/matchup/emission_udtf.py"
    "dbt/seeds/player_handedness.csv"
)

echo "[submit.sh] verifying source files exist in the repo"
for rel in "${PATHS[@]}"; do
    if [[ ! -f "${REPO_ROOT}/${rel}" ]]; then
        echo "ERROR: missing ${REPO_ROOT}/${rel}"
        exit 1
    fi
done

echo "[submit.sh] cancelling any RUNNING matchup job (one sink writer at a time)"
RUNNING_IDS="$(docker exec "$JM" /opt/flink/bin/flink list 2>/dev/null \
    | grep -i 'matchup_signals' | grep -oE '[0-9a-f]{32}' || true)"
if [[ -n "$RUNNING_IDS" ]]; then
    while read -r jid; do
        [[ -z "$jid" ]] && continue
        echo "[submit.sh]   cancelling ${jid}"
        docker exec "$JM" /opt/flink/bin/flink cancel "$jid" || true
    done <<< "$RUNNING_IDS"
    sleep 5
else
    echo "[submit.sh]   none running"
fi

echo "[submit.sh] staging code + seed under ${JM}:${STAGE} (clean copy)"
docker exec -u root "$JM" rm -rf "$STAGE"
docker exec -u root "$JM" mkdir -p "$STAGE"
for rel in "${PATHS[@]}"; do
    dst="${STAGE}/${rel}"
    docker exec -u root "$JM" mkdir -p "$(dirname "$dst")"
    docker cp "${REPO_ROOT}/${rel}" "${JM}:${dst}"
done
docker exec -u root "$JM" chown -R flink:flink "$STAGE"

# --pyFiles ships STAGE to every worker and puts it on their PYTHONPATH, so the
# taskmanager (a separate container) can import signals.* and read the seed.
# --python names the entrypoint script; the job's own imports resolve from the
# shipped files.
echo "[submit.sh] submitting via flink run --pyFiles ${STAGE} --python ${ENTRYPOINT}"
docker exec "$JM" /opt/flink/bin/flink run \
    --pyFiles "$STAGE" \
    --python "$ENTRYPOINT" \
    --detached

echo ""
echo "[submit.sh] submitted. Watch output with:"
echo "  docker logs -f bullpen-flink-tm"
echo "[submit.sh] confirm it is RUNNING with:"
echo "  docker exec ${JM} /opt/flink/bin/flink list"
