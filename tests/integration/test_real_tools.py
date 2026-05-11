"""Integration tests — real MCP instance with real mikr.us API calls via MCPWrapper."""

import time

import pytest

from mikrus_mcp.client import MikrusClient
from mikrus_mcp.server import mcp

from .conftest import MIKRUS_API_KEY, MIKRUS_SERVER_NAME, skip_if_no_key
from .mcp_wrapper import MCPWrapper


def _build_and_open(client: MikrusClient) -> MCPWrapper:
    """Create an MCPWrapper with a pre-opened real mikrus client."""
    lifespan_data = {
        "clients": {"default": client},
        "default": "default",
        "failed": {},
    }
    return MCPWrapper(mcp, lifespan_data)


@skip_if_no_key
@pytest.mark.asyncio
async def test_real_get_server_info() -> None:
    """Verify get_server_info reads real /info endpoint via MCP tool."""
    client = MikrusClient(
        base_url="https://api.mikr.us",
        api_key=MIKRUS_API_KEY,
        server_name=MIKRUS_SERVER_NAME,
    )
    await client.open()
    try:
        time.sleep(2.0)
        wrapper = _build_and_open(client)
        result = await wrapper.call_tool("get_server_info")
        assert result["success"] is True, f"Expected success, got: {result}"
        assert "server_id" in result["data"]
    finally:
        await client.close()


@skip_if_no_key
@pytest.mark.asyncio
async def test_real_list_servers() -> None:
    """Verify list_servers reads real /serwery endpoint via MCP tool."""
    client = MikrusClient(
        base_url="https://api.mikr.us",
        api_key=MIKRUS_API_KEY,
        server_name=MIKRUS_SERVER_NAME,
    )
    await client.open()
    try:
        time.sleep(2.0)
        wrapper = _build_and_open(client)
        result = await wrapper.call_tool("list_servers")
        assert result["success"] is True, f"Expected success, got: {result}"
        assert isinstance(result["data"], list)
    finally:
        await client.close()


@skip_if_no_key
@pytest.mark.asyncio
async def test_real_get_logs() -> None:
    """Verify get_logs reads real /logs endpoint via MCP tool."""
    client = MikrusClient(
        base_url="https://api.mikr.us",
        api_key=MIKRUS_API_KEY,
        server_name=MIKRUS_SERVER_NAME,
    )
    await client.open()
    try:
        time.sleep(2.0)
        wrapper = _build_and_open(client)
        result = await wrapper.call_tool("get_logs")
        assert result["success"] is True, f"Expected success, got: {result}"
        assert isinstance(result["data"], list)
    finally:
        await client.close()


@skip_if_no_key
@pytest.mark.asyncio
async def test_real_get_ports() -> None:
    """Verify get_ports reads real /porty endpoint via MCP tool."""
    client = MikrusClient(
        base_url="https://api.mikr.us",
        api_key=MIKRUS_API_KEY,
        server_name=MIKRUS_SERVER_NAME,
    )
    await client.open()
    try:
        time.sleep(2.0)
        wrapper = _build_and_open(client)
        result = await wrapper.call_tool("get_ports")
        assert result["success"] is True, f"Expected success, got: {result}"
        assert isinstance(result["data"], (dict, list))
    finally:
        await client.close()


@skip_if_no_key
@pytest.mark.asyncio
async def test_real_execute_command() -> None:
    """Verify execute_command runs a real command via /exec through MCP tool."""
    client = MikrusClient(
        base_url="https://api.mikr.us",
        api_key=MIKRUS_API_KEY,
        server_name=MIKRUS_SERVER_NAME,
    )
    await client.open()
    try:
        time.sleep(2.0)
        wrapper = _build_and_open(client)
        result = await wrapper.call_tool("execute_command", cmd="echo hello")
        assert result["success"] is True, f"Expected success, got: {result}"
        assert "output" in result["data"]
    finally:
        await client.close()
