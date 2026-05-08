"""Smoke tests — critical tools return success with mocked API."""

import json

import pytest
import respx

from mikrus_mcp.client import MikrusClient
from mikrus_mcp.server import _call_tool_logic as call_tool


@pytest.mark.asyncio
async def test_get_server_info_success() -> None:
    """Verify get_server_info returns success with mocked API."""
    client = MikrusClient("https://api.mikr.us", "test-key", "test-srv")
    with respx.mock:
        respx.post("https://api.mikr.us/info").respond(
            json={"server_id": "test-srv", "param_ram": "1024", "param_disk": "15"}
        )
        await client.open()
        result = await call_tool("get_server_info", {}, client=client)
        await client.close()

    data = json.loads(result[0].text)
    assert data["success"] is True
    assert "data" in data
    assert "server_id" in data["data"]


@pytest.mark.asyncio
async def test_list_servers_success() -> None:
    """Verify list_servers returns success with mocked API."""
    client = MikrusClient("https://api.mikr.us", "test-key", "test-srv")
    with respx.mock:
        respx.post("https://api.mikr.us/serwery").respond(json=[{"server_id": "srv1"}])
        await client.open()
        result = await call_tool("list_servers", {}, client=client)
        await client.close()

    data = json.loads(result[0].text)
    assert data["success"] is True
    assert isinstance(data["data"], list)


@pytest.mark.asyncio
async def test_execute_command_success() -> None:
    """Verify execute_command returns success with mocked API."""
    client = MikrusClient("https://api.mikr.us", "test-key", "test-srv")
    with respx.mock:
        respx.post("https://api.mikr.us/exec").respond(
            json={"output": "hello", "exit_code": 0}
        )
        await client.open()
        result = await call_tool("execute_command", {"cmd": "echo hello"}, client=client)
        await client.close()

    data = json.loads(result[0].text)
    assert data["success"] is True
    assert "output" in data["data"]


@pytest.mark.asyncio
async def test_get_logs_success() -> None:
    """Verify get_logs returns success with mocked API."""
    client = MikrusClient("https://api.mikr.us", "test-key", "test-srv")
    with respx.mock:
        respx.post("https://api.mikr.us/logs").respond(json=[{"id": "1", "task": "test"}])
        await client.open()
        result = await call_tool("get_logs", {}, client=client)
        await client.close()

    data = json.loads(result[0].text)
    assert data["success"] is True
    assert isinstance(data["data"], list)


@pytest.mark.asyncio
async def test_api_error_returns_failure() -> None:
    """Verify API errors return success=False."""
    client = MikrusClient("https://api.mikr.us", "test-key", "test-srv")
    with respx.mock:
        respx.post("https://api.mikr.us/info").respond(status_code=500, text="Boom")
        await client.open()
        result = await call_tool("get_server_info", {}, client=client)
        await client.close()

    data = json.loads(result[0].text)
    assert data["success"] is False
    assert "error" in data
