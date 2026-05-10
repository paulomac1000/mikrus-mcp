"""Smoke tests — response format compliance for all tools via REST bridge.

[RULE: TEST-HIERARCHY-3] Makes direct REST API calls. Skips when server not running.
[RULE: TEST-HIERARCHY-5] E2E tests verify full pipeline integrity.
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


TOOLS_NO_PARAMS = [
    "list_configured_servers",
]

TOOLS_WITH_PARAMS = {
    "execute_command": {"cmd": "echo test"},
}

ALL_TOOLS = list(TOOLS_NO_PARAMS) + list(TOOLS_WITH_PARAMS.keys())


@pytest.fixture(scope="module")
def client() -> httpx.Client:
    return httpx.Client(base_url=REST_BASE, timeout=10.0)


def test_all_tools_return_success_format(client: httpx.Client) -> None:
    """Verify every reachable tool returns {"success": True/False, ...} structure.

    Follows Canonical Template 12: compliance test verifies success field exists.
    """
    for tool_name in TOOLS_NO_PARAMS:
        r = client.post(f"/tools/{tool_name}", json={"params": {}})
        assert r.status_code == 200, f"Tool '{tool_name}' returned {r.status_code}"
        data = r.json()
        assert "success" in data, f"Tool '{tool_name}' missing 'success' field"
        assert isinstance(data["success"], bool), f"Tool '{tool_name}' success is not bool"

    for tool_name, params in TOOLS_WITH_PARAMS.items():
        r = client.post(f"/tools/{tool_name}", json={"params": params})
        assert r.status_code == 200, f"Tool '{tool_name}' returned {r.status_code}"
        data = r.json()
        assert "success" in data, f"Tool '{tool_name}' missing 'success' field"
        assert isinstance(data["success"], bool), f"Tool '{tool_name}' success is not bool"
