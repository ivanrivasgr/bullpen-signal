#!/usr/bin/env bash
# Copy runtime-mounted connector JARs onto Flink's classpath, then delegate to
# the official image entrypoint with the original jobmanager/taskmanager args.

set -euo pipefail

CONNECTOR_DIR="${FLINK_CONNECTOR_DIR:-/opt/flink/lib/connectors}"

if compgen -G "${CONNECTOR_DIR}/*.jar" >/dev/null; then
    echo "[start-flink] copying connector JARs from ${CONNECTOR_DIR} into /opt/flink/lib"
    for jar in "${CONNECTOR_DIR}"/*.jar; do
        case "$(basename "$jar")" in
            flink-avro-confluent-registry-*.jar)
                echo "[start-flink] skipping slim $(basename "$jar"); using flink-sql-avro-confluent-registry bundle"
                ;;
            *)
                cp -f "$jar" /opt/flink/lib/
                ;;
        esac
    done
else
    echo "[start-flink] no connector JARs found in ${CONNECTOR_DIR}"
fi

exec /docker-entrypoint.sh "$@"
