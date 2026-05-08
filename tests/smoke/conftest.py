"""Smoke test conftest — minimal, mock-based for reliable execution."""

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
MIKRUS_API_URL = os.getenv("MIKRUS_API_URL", "https://api.mikr.us")
MIKRUS_SERVER_NAME = os.getenv("MIKRUS_SERVER_NAME", "")

skip_if_no_key = pytest.mark.skipif(
    not MIKRUS_API_KEY or MIKRUS_API_KEY == "your_api_key_here",
    reason="Valid MIKRUS_API_KEY required for smoke tests",
)
