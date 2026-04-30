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
    "flink-sql-connector-kafka-3.4.0-1.20.jar|https://repo.maven.apache.org/maven2/org/apache/flink/flink-sql-connector-kafka/3.4.0-1.20/flink-sql-connector-kafka-3.4.0-1.20.jar"
    "flink-avro-1.20.0.jar|https://repo.maven.apache.org/maven2/org/apache/flink/flink-avro/1.20.0/flink-avro-1.20.0.jar"
    "flink-sql-avro-confluent-registry-1.20.0.jar|https://repo.maven.apache.org/maven2/org/apache/flink/flink-sql-avro-confluent-registry/1.20.0/flink-sql-avro-confluent-registry-1.20.0.jar"
    "avro-1.11.3.jar|https://repo.maven.apache.org/maven2/org/apache/avro/avro/1.11.3/avro-1.11.3.jar"
    "jackson-core-2.14.2.jar|https://repo.maven.apache.org/maven2/com/fasterxml/jackson/core/jackson-core/2.14.2/jackson-core-2.14.2.jar"
    "jackson-databind-2.14.2.jar|https://repo.maven.apache.org/maven2/com/fasterxml/jackson/core/jackson-databind/2.14.2/jackson-databind-2.14.2.jar"
    "jackson-annotations-2.14.2.jar|https://repo.maven.apache.org/maven2/com/fasterxml/jackson/core/jackson-annotations/2.14.2/jackson-annotations-2.14.2.jar"
    "kafka-schema-registry-client-7.5.3.jar|https://packages.confluent.io/maven/io/confluent/kafka-schema-registry-client/7.5.3/kafka-schema-registry-client-7.5.3.jar"
    "guava-32.0.1-jre.jar|https://repo.maven.apache.org/maven2/com/google/guava/guava/32.0.1-jre/guava-32.0.1-jre.jar"
    "failureaccess-1.0.1.jar|https://repo.maven.apache.org/maven2/com/google/guava/failureaccess/1.0.1/failureaccess-1.0.1.jar"
    "swagger-annotations-2.1.10.jar|https://repo.maven.apache.org/maven2/io/swagger/core/v3/swagger-annotations/2.1.10/swagger-annotations-2.1.10.jar"
    "commons-compress-1.21.jar|https://repo.maven.apache.org/maven2/org/apache/commons/commons-compress/1.21/commons-compress-1.21.jar"
    "snakeyaml-2.0.jar|https://repo.maven.apache.org/maven2/org/yaml/snakeyaml/2.0/snakeyaml-2.0.jar"
    "kafka-clients-7.5.3-ccs.jar|https://packages.confluent.io/maven/org/apache/kafka/kafka-clients/7.5.3-ccs/kafka-clients-7.5.3-ccs.jar"
    "hadoop-client-api-3.3.6.jar|https://repo.maven.apache.org/maven2/org/apache/hadoop/hadoop-client-api/3.3.6/hadoop-client-api-3.3.6.jar"
    "hadoop-client-runtime-3.3.6.jar|https://repo.maven.apache.org/maven2/org/apache/hadoop/hadoop-client-runtime/3.3.6/hadoop-client-runtime-3.3.6.jar"
    "iceberg-aws-bundle-1.10.1.jar|https://repo.maven.apache.org/maven2/org/apache/iceberg/iceberg-aws-bundle/1.10.1/iceberg-aws-bundle-1.10.1.jar"
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
