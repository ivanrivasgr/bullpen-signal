# Bullpen Signal — Flink 1.20.3 image with Python 3 + PyFlink installed.
#
# The official flink:1.20.3-scala_2.12-java11 image ships PyFlink as zips under
# /opt/flink/opt/python/ but does NOT include a Python interpreter. The
# `flink run -py` command therefore fails with "python3: command not found".
# This Dockerfile extends the official image with python3, pip, and the
# apache-flink Python package matching the cluster version.
#
# Why install apache-flink via pip when /opt/flink/opt/python/pyflink.zip
# already exists: pip handles the runtime dependencies (cloudpickle, py4j,
# pemja, numpy, pandas, etc.) that PyFlink expects on the Python side.
# Trying to use the bundled zip directly leaves those deps unresolved.

FROM flink:1.20.3-scala_2.12-java11

USER root

# Install python3, pip, and the build deps PyFlink wheels need at install time.
# `--no-install-recommends` keeps the image lean.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        python3-dev \
    && ln -sf /usr/bin/python3 /usr/bin/python \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install PyFlink matching the cluster version exactly. The base image
# (Flink 1.20.3 on Debian 11 / Bullseye) ships pip 20-21 which predates
# PEP 668, so --break-system-packages is neither needed nor recognized.
RUN pip3 install --no-cache-dir \
    apache-flink==1.20.0 \
    confluent-kafka[schema-registry]==2.4.0 \
    fastavro==1.9.7

# Verify Python and PyFlink are importable. Build fails fast if either broke.
# pyflink does not expose __version__ at module level (across both 1.x and 2.x);
# we import a real submodule instead, which fails loudly on broken installs.
RUN python3 --version \
    && python3 -c "from pyflink.datastream import StreamExecutionEnvironment; print('pyflink import ok')"

# Wrap the stock Flink entrypoint so connector JARs mounted at runtime are
# copied into /opt/flink/lib before the JVM starts. Flink's classpath scans
# JARs in /opt/flink/lib itself, not arbitrary nested directories.
COPY start-flink.sh /usr/local/bin/start-flink.sh

# Pre-create writable runtime dirs. Docker mounts named volumes as root by
# default; without this, the JobMaster fails to create per-job state subdirs.
RUN chmod +x /usr/local/bin/start-flink.sh \
    && mkdir -p /tmp/flink-checkpoints \
    && chown -R flink:flink /tmp/flink-checkpoints /opt/flink/lib

USER flink

ENTRYPOINT ["/usr/local/bin/start-flink.sh"]
