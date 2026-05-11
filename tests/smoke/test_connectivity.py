"""Smoke tests — API connectivity and health checks."""

import os

import httpx
import pytest

MIKRUS_API_KEY = os.getenv("MIKRUS_API_KEY", "")
MIKRUS_API_URL = os.getenv("MIKRUS_API_URL", "https://api.mikr.us")
MIKRUS_SERVER_NAME = os.getenv("MIKRUS_SERVER_NAME", "")

skip_if_no_key = pytest.mark.skipif(
    not MIKRUS_API_KEY or MIKRUS_API_KEY == "your_api_key_here",
    reason="Valid MIKRUS_API_KEY required for smoke tests",
)


@skip_if_no_key
def test_api_reachable() -> None:
    """Verify the mikr.us API is reachable."""
    response = httpx.get(f"{MIKRUS_API_URL}/", timeout=10.0)
    assert response.status_code in (200, 404, 405)


@skip_if_no_key
def test_info_endpoint_accessible() -> None:
    """Verify the /info endpoint responds without network error."""
    response = httpx.post(
        f"{MIKRUS_API_URL}/info",
        data={"key": MIKRUS_API_KEY, "srv": MIKRUS_SERVER_NAME},
        timeout=10.0,
    )
    assert response.status_code in (200, 429)


@skip_if_no_key
def test_stats_endpoint_returns_json() -> None:
    """Verify the /stats endpoint returns valid JSON when not rate limited."""
    response = httpx.post(
        f"{MIKRUS_API_URL}/stats",
        data={"key": MIKRUS_API_KEY, "srv": MIKRUS_SERVER_NAME},
        timeout=10.0,
    )
    assert response.status_code in (200, 429)
    if response.status_code == 200:
        data = response.json()
        assert isinstance(data, dict)
