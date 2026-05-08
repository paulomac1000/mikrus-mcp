"""Integration tests — real mikr.us API calls."""

import httpx
import pytest

from tests.integration.conftest import MIKRUS_API_KEY, MIKRUS_SERVER_NAME

MIKRUS_API_URL = "https://api.mikr.us"

skip_if_no_key = pytest.mark.skipif(
    not MIKRUS_API_KEY or MIKRUS_API_KEY == "your_api_key_here",
    reason="Valid MIKRUS_API_KEY required for integration tests",
)


def _assert_ok(response: httpx.Response) -> bool:
    """Return True if the response is 200, False if 429 (rate limited)."""
    assert response.status_code in (200, 429)
    return response.status_code == 200


@skip_if_no_key
def test_real_get_server_info() -> None:
    """Verify real /info endpoint returns server data."""
    response = httpx.post(
        f"{MIKRUS_API_URL}/info",
        data={"key": MIKRUS_API_KEY, "srv": MIKRUS_SERVER_NAME},
        timeout=15.0,
    )
    if _assert_ok(response):
        data = response.json()
        assert "server_id" in data


@skip_if_no_key
def test_real_get_logs_returns_list() -> None:
    """Verify real /logs endpoint returns a list."""
    response = httpx.post(
        f"{MIKRUS_API_URL}/logs",
        data={"key": MIKRUS_API_KEY, "srv": MIKRUS_SERVER_NAME},
        timeout=15.0,
    )
    if _assert_ok(response):
        data = response.json()
        assert isinstance(data, list)


@skip_if_no_key
def test_real_get_ports_returns_dict() -> None:
    """Verify real /porty endpoint returns port data."""
    response = httpx.post(
        f"{MIKRUS_API_URL}/porty",
        data={"key": MIKRUS_API_KEY, "srv": MIKRUS_SERVER_NAME},
        timeout=15.0,
    )
    if _assert_ok(response):
        data = response.json()
        assert isinstance(data, (dict, list))


@skip_if_no_key
def test_real_execute_command_echo() -> None:
    """Verify real /exec endpoint runs commands."""
    response = httpx.post(
        f"{MIKRUS_API_URL}/exec",
        data={"key": MIKRUS_API_KEY, "srv": MIKRUS_SERVER_NAME, "cmd": "echo hello"},
        timeout=20.0,
    )
    if _assert_ok(response):
        data = response.json()
        assert "output" in data


@skip_if_no_key
def test_real_get_server_stats() -> None:
    """Verify real /stats endpoint returns usage data."""
    response = httpx.post(
        f"{MIKRUS_API_URL}/stats",
        data={"key": MIKRUS_API_KEY, "srv": MIKRUS_SERVER_NAME},
        timeout=15.0,
    )
    if _assert_ok(response):
        data = response.json()
        assert isinstance(data, dict)
