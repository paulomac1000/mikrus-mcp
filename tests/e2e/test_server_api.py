"""E2E tests — full pipeline workflows via REST bridge.

[RULE: TEST-HIERARCHY-5] Exercises REST API endpoint calls to tool execution
and response validation. Skips when MCP server is not running.
"""

import os
import socket

import httpx
import pytest

REST_PORT = int(os.getenv("MCP_REST_PORT", "8301"))
REST_BASE = f"http://127.0.0.1:{REST_PORT}"


def _server_running() -> bool:
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


def test_health_and_tool_list(client: httpx.Client) -> None:
    """Verify health endpoint and tool listing."""
    r = client.get("/health")
    assert r.status_code == 200
    health = r.json()
    assert health["status"] == "healthy"
    assert health["tool_count"] == 32

    r = client.get("/tools")
    assert r.status_code == 200
    tools = r.json()
    assert tools["success"] is True
    assert len(tools["data"]) == 32


def test_list_configured_servers(client: httpx.Client) -> None:
    """Verify list_configured_servers returns server structure."""
    r = client.post("/tools/list_configured_servers", json={"params": {}})
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    inner = data["data"]
    assert "default_server" in inner
    assert "total_count" in inner
    assert "servers" in inner
    assert isinstance(inner["servers"], list)


def test_error_handling_invalid_tool(client: httpx.Client) -> None:
    """Verify unknown tool returns error."""
    r = client.post("/tools/nonexistent_tool", json={"params": {}})
    assert r.status_code in (200, 500)
    data = r.json()
    assert data["success"] is False
    assert "error" in data


def test_response_consistency(client: httpx.Client) -> None:
    """Verify multiple tools return consistent success/data/error format."""
    tools = [
        ("list_configured_servers", {}),
        ("execute_command", {"cmd": "echo test"}),
    ]
    for tool_name, params in tools:
        r = client.post(f"/tools/{tool_name}", json={"params": params})
        assert r.status_code == 200, f"Tool '{tool_name}' returned {r.status_code}"
        data = r.json()
        assert "success" in data, f"Tool '{tool_name}' missing 'success'"
        assert isinstance(data["success"], bool), f"Tool '{tool_name}' success not bool"
