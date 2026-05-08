"""Root test configuration — environment loading only."""

import os
from pathlib import Path


def _load_env() -> None:
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


_load_env()

MIKRUS_API_KEY = os.getenv("MIKRUS_API_KEY", "")
MIKRUS_API_URL = os.getenv("MIKRUS_API_URL", "https://api.mikr.us")
