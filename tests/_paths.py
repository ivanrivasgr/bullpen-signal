"""Canonical repository root for tests that read repo files.

Several tests assert on the contents of committed files — dbt models,
SQL, YAML, the smoke job. They must locate those files relative to the
repository, not relative to the current working directory, or they pass
when pytest runs from the repo root and fail from anywhere else (a CI
runner that changes directory, an IDE test runner, a developer running a
single test from a subfolder). This module derives the root once from
its own location so every test resolves files the same way regardless of
where pytest is invoked.
"""

from __future__ import annotations

from pathlib import Path

# tests/_paths.py -> tests/ -> repo root
REPO_ROOT = Path(__file__).resolve().parents[1]
