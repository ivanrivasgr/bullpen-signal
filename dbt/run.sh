#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

python infra/scripts/refresh_iceberg_sources.py

LOCATION="$(
python - <<'PY'
import json
from pathlib import Path

sources = json.loads(Path("dbt/.iceberg_sources.json").read_text())
print(sources["bronze.pitches"]["metadata_location"])
PY
)"

cd dbt

if [ ! -f profiles.yml ]; then
  echo "profiles.yml not found. Copy profiles.yml.example to profiles.yml before running dbt."
  exit 1
fi

dbt run --vars "{bronze_pitches_location: '$LOCATION'}" "$@"

cd "$REPO_ROOT"
python infra/scripts/publish_dbt_silver.py "$@"
