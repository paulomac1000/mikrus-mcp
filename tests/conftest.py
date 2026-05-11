"""Root test configuration — environment loading only."""

import os

from tests._env_loader import load_test_env

load_test_env()

MIKRUS_API_KEY = os.getenv("MIKRUS_API_KEY", "")
MIKRUS_API_URL = os.getenv("MIKRUS_API_URL", "https://api.mikr.us")
