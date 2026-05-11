"""Smoke test conftest — minimal, mock-based for reliable execution."""

import os

import pytest

from tests._env_loader import load_test_env

load_test_env()

MIKRUS_API_KEY = os.getenv("MIKRUS_API_KEY", "")
MIKRUS_API_URL = os.getenv("MIKRUS_API_URL", "https://api.mikr.us")
MIKRUS_SERVER_NAME = os.getenv("MIKRUS_SERVER_NAME", "")

skip_if_no_key = pytest.mark.skipif(
    not MIKRUS_API_KEY or MIKRUS_API_KEY == "your_api_key_here",
    reason="Valid MIKRUS_API_KEY required for smoke tests",
)
