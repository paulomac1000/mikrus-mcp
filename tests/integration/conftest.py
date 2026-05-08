"""Integration test conftest — real credentials, real MCP wrapper."""

import os
from pathlib import Path

import pytest

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

MIKRUS_API_KEY = os.getenv("MIKRUS_API_KEY", "")
MIKRUS_SERVER_NAME = os.getenv("MIKRUS_SERVER_NAME", "")

pytestmark = pytest.mark.skipif(
    not MIKRUS_API_KEY or MIKRUS_API_KEY == "your_api_key_here",
    reason="MIKRUS_API_KEY required for integration tests",
)
