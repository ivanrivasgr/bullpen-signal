"""Shared helpers for local Iceberg file IO configuration."""

from __future__ import annotations

import os


def iceberg_file_io_properties() -> dict[str, str]:
    """Return local MinIO/S3 properties for PyIceberg reads."""
    return {
        "s3.endpoint": os.getenv("S3_ENDPOINT", "http://localhost:9000"),
        "s3.access-key-id": os.getenv("S3_ACCESS_KEY", "minioadmin"),
        "s3.secret-access-key": os.getenv("S3_SECRET_KEY", "minioadmin"),
        "s3.region": os.getenv("S3_REGION", "us-east-1"),
        "s3.path-style-access": "true",
    }
