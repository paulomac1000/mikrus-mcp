"""Smoke tests — critical tools via REST bridge.

[RULE: TEST-HIERARCHY-3] Makes direct REST API calls to localhost.
Skips when MCP server with REST bridge is not running.
"""

import os
import socket

import httpx
import pytest

REST_PORT = int(os.getenv("MCP_REST_PORT", "8301"))
REST_BASE = f"http://127.0.0.1:{REST_PORT}"


def _server_running() -> bool:
    """Dynamic socket check — skips when server is not running."""
    try:
        s = socket.create_connection(("127.0.0.1", REST_PORT), timeout=1.0)
        s.close()
        return True
    except (TimeoutError, ConnectionRefusedError, OSError):
        return False


pytestmark = pytest.mark.skipif(
    not _server_running(), reason="MCP server not running on port " + str(REST_PORT)
)


@pytest.fixture(scope="module")
def client() -> httpx.Client:
    return httpx.Client(base_url=REST_BASE, timeout=10.0)


def test_health_endpoint(client: httpx.Client) -> None:
    """Verify /health returns healthy status with tool count."""
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "healthy"
    assert data["tool_count"] == 33


def test_tools_list(client: httpx.Client) -> None:
    """Verify /tools returns tool names."""
    r = client.get("/tools")
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    assert len(data["data"]) > 0


def test_get_server_info(client: httpx.Client) -> None:
    """Verify get_server_info returns structured response via REST."""
    r = client.post("/tools/get_server_info", json={"params": {}})
    assert r.status_code == 200
    data = r.json()
    assert "success" in data
    assert isinstance(data["success"], bool)


def test_execute_command(client: httpx.Client) -> None:
    """Verify execute_command returns structured response via REST."""
    r = client.post("/tools/execute_command", json={"params": {"cmd": "echo hello"}})
    assert r.status_code == 200
    data = r.json()
    assert "success" in data
