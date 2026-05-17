"""Unit tests for tool registration — verifies register_*_tools(mock_mcp).

Follows [RULE: TEST-REG-2]: tests call registration functions on mock_mcp,
retrieve tools via mock_mcp.get_tool(), invoke them, and assert the response.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from mikrus_mcp.server import mcp as real_mcp
from mikrus_mcp.tools.capabilities import register_capability_tools
from mikrus_mcp.tools.container_journal import register_container_journal_tools
from mikrus_mcp.tools.discovery import register_discovery_tools
from mikrus_mcp.tools.mikrus_api import register_mikrus_tools
from mikrus_mcp.tools.system import register_system_tools

# --- Registration verification tests ---


def test_register_mikrus_tools_registers_all(mock_mcp: MagicMock) -> None:
    """Verify register_mikrus_tools registers all 11 mikrus-only tools."""
    register_mikrus_tools(mock_mcp)
    expected = [
        "get_server_info",
        "list_servers",
        "get_server_stats",
        "restart_server",
        "get_logs",
        "get_log_by_id",
        "boost_server",
        "get_db_info",
        "get_ports",
        "get_cloud",
        "assign_domain",
    ]
    for name in expected:
        assert mock_mcp.get_tool(name) is not None, f"Tool '{name}' not registered"


def test_register_system_tools_registers_all(mock_mcp: MagicMock) -> None:
    """Verify register_system_tools registers all 14 system tools."""
    register_system_tools(mock_mcp)
    expected = [
        "execute_command",
        "read_file",
        "write_file",
        "manage_service",
        "analyze_disk",
        "check_port",
        "manage_process",
        "update_system",
        "list_directory",
        "tail_file",
        "search_in_files",
        "get_memory_info",
        "get_network_info",
        "get_process_tree",
    ]
    for name in expected:
        assert mock_mcp.get_tool(name) is not None, f"Tool '{name}' not registered"


def test_register_container_journal_tools_registers_all(mock_mcp: MagicMock) -> None:
    """Verify register_container_journal_tools registers all 6 tools."""
    register_container_journal_tools(mock_mcp)
    expected = [
        "list_docker_containers",
        "get_docker_logs",
        "get_docker_stats",
        "get_journal_logs",
        "find_system_errors",
        "search_journal_logs",
    ]
    for name in expected:
        assert mock_mcp.get_tool(name) is not None, f"Tool '{name}' not registered"


def test_register_discovery_tools_registers_all(mock_mcp: MagicMock) -> None:
    """Verify register_discovery_tools registers the discovery tool."""
    register_discovery_tools(mock_mcp)
    tool = mock_mcp.get_tool("list_configured_servers")
    assert tool is not None, "list_configured_servers not registered"


def test_register_capability_tools_registers(mock_mcp: MagicMock) -> None:
    """Verify register_capability_tools registers the capabilities tool."""
    register_capability_tools(mock_mcp)
    tool = mock_mcp.get_tool("describe_mikrus_capabilities")
    assert tool is not None, "describe_mikrus_capabilities not registered"


# --- Mikrus tool success paths via registration ---


@pytest.mark.asyncio
async def test_get_server_info_via_registration(
    mock_mcp: MagicMock,
    mcp_context: MagicMock,
    mock_mikrus: MagicMock,
) -> None:
    register_mikrus_tools(mock_mcp)
    tool_fn = mock_mcp.get_tool("get_server_info")
    assert tool_fn is not None

    mock_mikrus.get_server_info.return_value = {"server_id": "srv1", "param_ram": "1024"}
    with patch.object(real_mcp, "get_context", return_value=mcp_context):
        result = await tool_fn()

    data = json.loads(result)
    assert data["success"] is True
    assert data["data"]["server_id"] == "srv1"


@pytest.mark.asyncio
async def test_list_servers_via_registration(
    mock_mcp: MagicMock,
    mcp_context: MagicMock,
    mock_mikrus: MagicMock,
) -> None:
    register_mikrus_tools(mock_mcp)
    tool_fn = mock_mcp.get_tool("list_servers")
    assert tool_fn is not None

    mock_mikrus.list_servers.return_value = [{"server_id": "srv1"}]
    with patch.object(real_mcp, "get_context", return_value=mcp_context):
        result = await tool_fn()

    data = json.loads(result)
    assert data["success"] is True
    assert len(data["data"]) == 1


@pytest.mark.asyncio
async def test_execute_command_via_registration(
    mock_mcp: MagicMock,
    mcp_context: MagicMock,
    mock_mikrus: MagicMock,
) -> None:
    register_system_tools(mock_mcp)
    tool_fn = mock_mcp.get_tool("execute_command")
    assert tool_fn is not None

    mock_mikrus.execute_command.return_value = {"output": "hello", "exit_code": 0}
    with patch.object(real_mcp, "get_context", return_value=mcp_context):
        result = await tool_fn("echo hello")

    data = json.loads(result)
    assert data["success"] is True
    assert data["data"]["output"] == "hello"


@pytest.mark.asyncio
async def test_list_configured_servers_via_registration(
    mock_mcp: MagicMock,
    mcp_context: MagicMock,
    mock_mikrus: MagicMock,
    mock_ssh: MagicMock,
) -> None:
    register_discovery_tools(mock_mcp)
    tool_fn = mock_mcp.get_tool("list_configured_servers")
    assert tool_fn is not None

    with patch.object(real_mcp, "get_context", return_value=mcp_context):
        result = await tool_fn()

    data = json.loads(result)
    assert data["success"] is True
    assert data["data"]["total_count"] == 2
    assert data["data"]["connected_count"] == 2


# --- Exception handler tests via registration ---


@pytest.mark.asyncio
async def test_mikrus_tool_error_via_registration(
    mock_mcp: MagicMock,
    mcp_context: MagicMock,
    mock_mikrus: MagicMock,
) -> None:
    """[RULE: TEST-REG-3] Verify exception is caught and wrapped."""
    register_mikrus_tools(mock_mcp)
    tool_fn = mock_mcp.get_tool("get_server_info")
    assert tool_fn is not None

    mock_mikrus.get_server_info.side_effect = RuntimeError("boom")
    with patch.object(real_mcp, "get_context", return_value=mcp_context):
        result = await tool_fn()

    data = json.loads(result)
    assert data["success"] is False
    assert "boom" in str(data["error"])


@pytest.mark.asyncio
async def test_system_tool_error_via_registration(
    mock_mcp: MagicMock,
    mcp_context: MagicMock,
    mock_mikrus: MagicMock,
) -> None:
    """[RULE: TEST-REG-3] Verify exception is caught and wrapped."""
    register_system_tools(mock_mcp)
    tool_fn = mock_mcp.get_tool("execute_command")
    assert tool_fn is not None

    mock_mikrus.execute_command.side_effect = RuntimeError("timeout")
    with patch.object(real_mcp, "get_context", return_value=mcp_context):
        result = await tool_fn("echo hello")

    data = json.loads(result)
    assert data["success"] is False
    assert "timeout" in str(data["error"])


# --- Wrong server type tests via registration ---


@pytest.mark.asyncio
async def test_mikrus_tool_on_ssh_returns_error(
    mock_mcp: MagicMock,
    mcp_context: MagicMock,
) -> None:
    register_mikrus_tools(mock_mcp)
    tool_fn = mock_mcp.get_tool("get_server_info")
    assert tool_fn is not None

    with patch.object(real_mcp, "get_context", return_value=mcp_context):
        result = await tool_fn("beta")

    data = json.loads(result)
    assert data["success"] is False
    assert "mikrus" in str(data["error"]).lower()


# --- Capabilities tool tests ---


@pytest.mark.asyncio
async def test_describe_mikrus_capabilities_via_registration(
    mock_mcp: MagicMock,
) -> None:
    """[RULE: TEST-REG-2] The capabilities tool is zero-I/O and returns the catalog."""
    register_capability_tools(mock_mcp)
    tool_fn = mock_mcp.get_tool("describe_mikrus_capabilities")
    assert tool_fn is not None

    result = await tool_fn()
    data = json.loads(result)
    assert data["success"] is True
    assert "tools" in data["data"]
    assert data["data"]["tool_count"] > 0


@pytest.mark.asyncio
async def test_describe_mikrus_capabilities_error(
    mock_mcp: MagicMock,
) -> None:
    """[RULE: TEST-REG-3] Verify exception is caught and wrapped."""
    from mikrus_mcp.tools import capabilities as cap_mod

    register_capability_tools(mock_mcp)
    tool_fn = mock_mcp.get_tool("describe_mikrus_capabilities")
    assert tool_fn is not None

    with patch.object(
        cap_mod, "_do_describe_mikrus_capabilities", side_effect=RuntimeError("boom")
    ):
        result = await tool_fn()

    data = json.loads(result)
    assert data["success"] is False
    assert "boom" in str(data["error"])
