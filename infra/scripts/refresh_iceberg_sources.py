"""Refresh local dbt Iceberg source metadata locations.

dbt-duckdb does not resolve the Iceberg REST catalog directly. This helper
fetches the current Iceberg metadata-location from the local REST catalog and
writes dbt/.iceberg_sources.json for the dbt wrapper script.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import urlopen

ICEBERG_REST_URI = "http://localhost:8181"
OUTPUT_PATH = Path("dbt/.iceberg_sources.json")


def _table_metadata_location(identifier: str) -> str:
    namespace, table = identifier.split(".", 1)
    url = f"{ICEBERG_REST_URI}/v1/namespaces/{namespace}/tables/{table}"
    with urlopen(url, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))

    metadata_location = payload.get("metadata-location") or payload.get("metadataLocation")
    if not metadata_location:
        raise RuntimeError(f"No metadata-location found for {identifier}")

    return metadata_location


def refresh_sources() -> dict[str, dict[str, str]]:
    """Refresh known Iceberg source metadata locations."""
    now = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    sources = {
        "bronze.pitches": {
            "metadata_location": _table_metadata_location("bronze.pitches"),
            "refreshed_at": now,
        }
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(sources, indent=2) + "\n")
    return sources


def main() -> None:
    sources = refresh_sources()
    print(f"ok: wrote {OUTPUT_PATH}")
    for identifier, values in sources.items():
        print(f"ok: {identifier} -> {values['metadata_location']}")


if __name__ == "__main__":
    main()
