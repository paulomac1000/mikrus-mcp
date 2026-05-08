"""E2E tests — full pipeline workflows and error handling."""

import json

import pytest
import respx

from mikrus_mcp.client import MikrusClient
from mikrus_mcp.server import _call_tool_logic as call_tool

MIKRUS_API_URL = "https://api.mikr.us"


@pytest.mark.asyncio
async def test_context_workflow() -> None:
    """Simulate a full context workflow: list servers -> get info -> get logs."""
    client = MikrusClient(MIKRUS_API_URL, "test-key", "test-srv")

    with respx.mock:
        respx.post(f"{MIKRUS_API_URL}/serwery").respond(
            json=[{"server_id": "test-srv", "param_ram": "1024"}]
        )
        respx.post(f"{MIKRUS_API_URL}/info").respond(
            json={"server_id": "test-srv", "param_ram": "1024", "param_disk": "15"}
        )
        respx.post(f"{MIKRUS_API_URL}/logs").respond(
            json=[{"id": "1", "task": "restart", "date": "2025-01-01", "result": "OK"}]
        )

        await client.open()

        # Step 1: List servers
        result = await call_tool("list_servers", {}, client=client)
        data = json.loads(result[0].text)
        assert data["success"] is True
        assert len(data["data"]) > 0

        # Step 2: Get server info
        result = await call_tool("get_server_info", {}, client=client)
        data = json.loads(result[0].text)
        assert data["success"] is True
        assert data["data"]["server_id"] == "test-srv"

        # Step 3: Get logs
        result = await call_tool("get_logs", {}, client=client)
        data = json.loads(result[0].text)
        assert data["success"] is True
        assert len(data["data"]) > 0
        assert data["data"][0]["task"] == "restart"

        await client.close()


@pytest.mark.asyncio
async def test_error_handling_invalid_tool() -> None:
    """Verify unknown tool returns error in success format."""
    client = MikrusClient(MIKRUS_API_URL, "test-key", "test-srv")
    await client.open()
    result = await call_tool("nonexistent_tool", {}, client=client)
    await client.close()

    data = json.loads(result[0].text)
    assert data["success"] is False
    assert "error" in data


@pytest.mark.asyncio
async def test_error_handling_api_error() -> None:
    """Verify HTTP error from API is properly wrapped."""
    client = MikrusClient(MIKRUS_API_URL, "test-key", "test-srv")

    with respx.mock:
        respx.post(f"{MIKRUS_API_URL}/info").respond(status_code=503, text="Service Unavailable")
        await client.open()
        result = await call_tool("get_server_info", {}, client=client)
        await client.close()

    data = json.loads(result[0].text)
    assert data["success"] is False
    assert "error" in data
    assert "503" in data["error"] or "Service" in data["error"]


@pytest.mark.asyncio
async def test_response_consistency_across_tools() -> None:
    """Verify all mockable tools return consistent {"success": ..., "data"/"error": ...} format."""
    client = MikrusClient(MIKRUS_API_URL, "test-key", "test-srv")

    tools = [
        ("get_server_info", {}),
        ("list_servers", {}),
        ("get_server_stats", {}),
        ("get_logs", {}),
        ("get_memory_info", {}),
        ("get_process_tree", {}),
    ]

    with respx.mock:
        respx.post(f"{MIKRUS_API_URL}/info").respond(
            json={"server_id": "srv", "param_ram": "1024"}
        )
        respx.post(f"{MIKRUS_API_URL}/serwery").respond(json=[])
        respx.post(f"{MIKRUS_API_URL}/stats").respond(json={"uptime": "1d"})
        respx.post(f"{MIKRUS_API_URL}/logs").respond(json=[])
        respx.post(f"{MIKRUS_API_URL}/exec").respond(
            json={"output": "test", "exit_code": 0}
        )

        await client.open()

        for tool_name, args in tools:
            result = await call_tool(tool_name, args, client=client)
            data = json.loads(result[0].text)
            assert "success" in data, f"Tool '{tool_name}' missing 'success'"
            assert isinstance(data["success"], bool), (
                f"Tool '{tool_name}' success not bool"
            )
            if data["success"]:
                assert "data" in data, f"Tool '{tool_name}' missing 'data' when success=True"
            else:
                assert "error" in data, f"Tool '{tool_name}' missing 'error' when success=False"

        await client.close()
