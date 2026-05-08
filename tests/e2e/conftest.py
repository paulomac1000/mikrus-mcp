"""E2E test conftest — minimal."""

import os
from pathlib import Path

import pytest


def _load_env() -> None:
    env_paths = [Path(".env")]
    for env_path in env_paths:
        if env_path.exists():
            try:
                for line in env_path.read_text().splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, value = line.partition("=")
                        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
            except Exception:
                pass


_load_env()

MIKRUS_API_KEY = os.getenv("MIKRUS_API_KEY", "")

pytestmark = pytest.mark.skipif(
    not MIKRUS_API_KEY or MIKRUS_API_KEY == "your_api_key_here",
    reason="MIKRUS_API_KEY required for e2e tests",
)
