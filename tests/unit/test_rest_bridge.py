"""Unit tests for REST bridge endpoints."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.testclient import TestClient

from mikrus_mcp.rest_bridge import create_rest_app


@pytest.fixture
def mock_mcp() -> MagicMock:
    """Create a mock MCP instance with lifespan data and tools."""
    mcp = MagicMock()

    mcp._lifespan_data = {
        "clients": {"alpha": MagicMock(), "beta": MagicMock()},
        "default": "alpha",
        "failed": {},
    }

    class MockTool:
        def __init__(self, name: str) -> None:
            self.name = name

    mcp.list_tools = AsyncMock(
        return_value=[
            MockTool("get_server_info"),
            MockTool("execute_command"),
            MockTool("list_servers"),
        ]
    )

    mcp.call_tool = AsyncMock(return_value=[])

    return mcp


@pytest.fixture
def client(mock_mcp: MagicMock) -> TestClient:
    """Create a Starlette TestClient for the REST bridge."""
    app = create_rest_app(mock_mcp)
    return TestClient(app)


def test_health_endpoint(client: TestClient) -> None:
    """GET /health returns healthy with tool_count and version."""
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "healthy"
    assert data["tool_count"] == 33
    assert "tools_version" in data


def test_health_endpoint_api_prefix(client: TestClient) -> None:
    """GET /api/health returns the same as /health."""
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "healthy"


def test_tools_list(client: TestClient, mock_mcp: MagicMock) -> None:
    """GET /tools returns tool names from mcp.list_tools()."""
    r = client.get("/tools")
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    assert len(data["data"]) == 3
    assert data["data"][0]["name"] == "get_server_info"


def test_tools_list_api_prefix(client: TestClient) -> None:
    """GET /api/tools returns the same as /tools."""
    r = client.get("/api/tools")
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True


def test_call_tool_no_lifespan() -> None:
    """POST /tools/{name} returns 503 when lifespan is not initialized."""
    mcp = MagicMock()
    mcp._lifespan_data = None
    app = create_rest_app(mcp)
    test_client = TestClient(app)

    r = test_client.post("/tools/get_server_info", json={"params": {}})
    assert r.status_code == 503
    data = r.json()
    assert data["success"] is False
    assert "not initialized" in data["error"]


def test_call_tool_empty_body(client: TestClient, mock_mcp: MagicMock) -> None:
    """POST /tools/{name} with empty body uses default empty params."""
    r = client.post("/tools/get_server_info")
    assert r.status_code == 200
    mock_mcp.call_tool.assert_called_once()


def test_call_tool_with_params(client: TestClient, mock_mcp: MagicMock) -> None:
    """POST /tools/{name} passes params to mcp.call_tool."""
    expected = {"server": "alpha"}
    r = client.post("/tools/get_server_info", json={"params": expected})
    assert r.status_code == 200
    mock_mcp.call_tool.assert_called_once_with("get_server_info", expected)


def test_manifest_valid_tool(client: TestClient) -> None:
    """GET /tools/{name}/manifest returns manifest for a known tool."""
    r = client.get("/tools/get_server_info/manifest")
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    assert data["data"]["risk"] == "READ"


def test_manifest_invalid_tool(client: TestClient) -> None:
    """GET /tools/{name}/manifest returns 404 for unknown tool."""
    r = client.get("/tools/nonexistent_tool/manifest")
    assert r.status_code == 404
    data = r.json()
    assert data["success"] is False


def test_manifest_api_prefix(client: TestClient) -> None:
    """GET /api/tools/{name}/manifest works the same."""
    r = client.get("/api/tools/get_server_info/manifest")
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True


def test_call_tool_returns_text_content(client: TestClient, mock_mcp: MagicMock) -> None:
    """POST /tools/{name} handles list of TextContent from FastMCP."""
    from mcp.types import TextContent

    mock_mcp.call_tool.return_value = [
        TextContent(type="text", text='{"success": true, "data": {"key": "value"}}')
    ]

    r = client.post("/tools/execute_command", json={"params": {"cmd": "echo hello"}})
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    assert data["data"]["key"] == "value"


def test_call_tool_tuple_result(client: TestClient, mock_mcp: MagicMock) -> None:
    """POST /tools/{name} handles FastMCP 1.27+ tuple return (list, dict)."""
    from mcp.types import TextContent

    content = [TextContent(type="text", text='{"success": true, "data": "tuple handled"}')]
    mock_mcp.call_tool.return_value = (content, {"result": "structured"})

    r = client.post("/tools/get_server_info", json={"params": {}})
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    assert data["data"] == "tuple handled"


def test_call_tool_exception(client: TestClient, mock_mcp: MagicMock) -> None:
    """POST /tools/{name} returns 500 when mcp.call_tool raises."""
    mock_mcp.call_tool.side_effect = RuntimeError("connection failed")

    r = client.post("/tools/get_server_info", json={"params": {}})
    assert r.status_code == 500
    data = r.json()
    assert data["success"] is False
    assert "connection failed" in data["error"]
