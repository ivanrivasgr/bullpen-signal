#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

# Make repo modules (lakehouse, infra) importable when scripts run.
export PYTHONPATH="$(pwd):${PYTHONPATH:-}"

# Disable dbt anonymous usage tracking. Snowplow tracker crashes WSL2
# kernel 6.6.87+ on flush; documented in ADR 0009 Update 2026-05-06.
export DBT_SEND_ANONYMOUS_USAGE_STATS=False

python infra/scripts/refresh_iceberg_sources.py

LOCATION=$(python -c "import json; print(json.load(open('dbt/.iceberg_sources.json'))['bronze.pitches']['metadata_location'])")

python infra/scripts/materialize_dbt_sources.py --metadata-location "$LOCATION"

cd dbt
dbt run --profiles-dir . "$@"
