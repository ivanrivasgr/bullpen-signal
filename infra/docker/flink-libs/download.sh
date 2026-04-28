#!/usr/bin/env bash
# Download Flink connector JARs into infra/docker/flink-libs/.
# Idempotent: skips JARs that already exist with non-zero size.
#
# Usage: bash infra/docker/flink-libs/download.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Format: filename|url
declare -a JARS=(
    "flink-connector-kafka-3.4.0-1.20.jar|https://repo.maven.apache.org/maven2/org/apache/flink/flink-connector-kafka/3.4.0-1.20/flink-connector-kafka-3.4.0-1.20.jar"
    "flink-sql-connector-kafka-3.4.0-1.20.jar|https://repo.maven.apache.org/maven2/org/apache/flink/flink-sql-connector-kafka/3.4.0-1.20/flink-sql-connector-kafka-3.4.0-1.20.jar"
    "flink-avro-1.20.0.jar|https://repo.maven.apache.org/maven2/org/apache/flink/flink-avro/1.20.0/flink-avro-1.20.0.jar"
    "flink-avro-confluent-registry-1.20.0.jar|https://repo.maven.apache.org/maven2/org/apache/flink/flink-avro-confluent-registry/1.20.0/flink-avro-confluent-registry-1.20.0.jar"
    "iceberg-flink-runtime-1.20-1.10.1.jar|https://repo.maven.apache.org/maven2/org/apache/iceberg/iceberg-flink-runtime-1.20/1.10.1/iceberg-flink-runtime-1.20-1.10.1.jar"
)

echo "Downloading Flink connector JARs to: $SCRIPT_DIR"
echo ""

for entry in "${JARS[@]}"; do
    filename="${entry%%|*}"
    url="${entry##*|}"

    if [[ -f "$filename" && -s "$filename" ]]; then
        size=$(du -h "$filename" | cut -f1)
        echo "  [skip] $filename already exists ($size)"
        continue
    fi

    echo "  [get]  $filename"
    if curl --fail --location --silent --show-error --output "$filename" "$url"; then
        size=$(du -h "$filename" | cut -f1)
        echo "         -> downloaded ($size)"
    else
        echo "         -> FAILED. URL: $url"
        rm -f "$filename"  # remove partial download
        exit 1
    fi
done

echo ""
echo "Done. Files in $SCRIPT_DIR:"
ls -lh *.jar 2>/dev/null || echo "  (none found — something went wrong)"
