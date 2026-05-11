"""Shared environment loader for test conftest files."""

import os
from pathlib import Path


def load_test_env() -> None:
    """Load environment variables from .env file if available."""
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
