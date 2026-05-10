"""Integration test conftest — real credentials, tool registration, skip logic."""

import os
from pathlib import Path

import pytest

from mikrus_mcp.server import mcp
from mikrus_mcp.tools.container_journal import register_container_journal_tools
from mikrus_mcp.tools.discovery import register_discovery_tools
from mikrus_mcp.tools.mikrus_api import register_mikrus_tools
from mikrus_mcp.tools.system import register_system_tools


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
MIKRUS_SERVER_NAME = os.getenv("MIKRUS_SERVER_NAME", "")

skip_if_no_key = pytest.mark.skipif(
    not MIKRUS_API_KEY or MIKRUS_API_KEY == "your_api_key_here",
    reason="Valid MIKRUS_API_KEY required for integration tests",
)

# Register all tool modules once at import time
register_mikrus_tools(mcp)
register_system_tools(mcp)
register_container_journal_tools(mcp)
register_discovery_tools(mcp)
