"""E2E test conftest — minimal."""

import os

from tests._env_loader import load_test_env

load_test_env()

MIKRUS_API_KEY = os.getenv("MIKRUS_API_KEY", "")
