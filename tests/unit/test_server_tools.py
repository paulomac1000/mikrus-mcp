"""Unit tests for MCP server tool handlers — direct call with mocked MCP context."""

import json
from unittest.mock import MagicMock, patch

import pytest

from mikrus_mcp.server import (
    _error_response,
    _get_client,
    _success_response,
    analyze_disk_tool,
    assign_domain_tool,
    boost_server_tool,
    check_port_tool,
    execute_command_tool,
    find_system_errors_tool,
    get_cloud_tool,
    get_db_info_tool,
    get_docker_logs_tool,
    get_docker_stats_tool,
    get_journal_logs_tool,
    get_log_by_id_tool,
    get_logs_tool,
    get_memory_info_tool,
    get_network_info_tool,
    get_ports_tool,
    get_process_tree_tool,
    get_server_info_tool,
    get_server_stats_tool,
    list_configured_servers_tool,
    list_directory_tool,
    list_docker_containers_tool,
    list_servers_tool,
    manage_process_tool,
    manage_service_tool,
    mcp,
    read_file_tool,
    restart_server_tool,
    search_in_files_tool,
    search_journal_logs_tool,
    tail_file_tool,
    update_system_tool,
    write_file_tool,
)

# === Helper function tests ===


def test_success_response() -> None:
    result = json.loads(_success_response({"key": "value"}))
    assert result["success"] is True
    assert result["data"] == {"key": "value"}


def test_error_response() -> None:
    result = json.loads(_error_response("something broke"))
    assert result["success"] is False
    assert result["error"] == "something broke"


def test_get_client_default(mcp_context: MagicMock) -> None:
    with patch.object(mcp, "get_context", return_value=mcp_context):
        client = _get_client()
    assert client is mcp_context.request_context.lifespan_context["clients"]["alpha"]


def test_get_client_explicit(mcp_context: MagicMock) -> None:
    with patch.object(mcp, "get_context", return_value=mcp_context):
        client = _get_client("beta")
    assert client is mcp_context.request_context.lifespan_context["clients"]["beta"]


def test_get_client_unknown(mcp_context: MagicMock) -> None:
    with patch.object(mcp, "get_context", return_value=mcp_context):
        with pytest.raises(ValueError, match="Unknown server"):
            _get_client("unknown")


# === Mikrus-only tools — success paths ===


MIKRUS_TOOLS_NO_ARGS = [
    (get_server_info_tool, "get_server_info", {}),
    (list_servers_tool, "list_servers", []),
    (get_server_stats_tool, "get_server_stats", {"uptime": "1d"}),
    (restart_server_tool, "restart_server", {"raw": "OK"}),
    (get_logs_tool, "get_logs", []),
    (boost_server_tool, "boost_server", {"status": "ok"}),
    (get_db_info_tool, "get_db_info", {"host": "db"}),
    (get_ports_tool, "get_ports", {"tcp": [], "udp": []}),
    (get_cloud_tool, "get_cloud", {"services": []}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_fn, method_name, return_value", MIKRUS_TOOLS_NO_ARGS)
async def test_mikrus_tools_success(
    tool_fn: object,
    method_name: str,
    return_value: object,
    mcp_context: MagicMock,
    mock_mikrus: MagicMock,
) -> None:
    mock_method = getattr(mock_mikrus, method_name)
    mock_method.return_value = return_value

    with patch.object(mcp, "get_context", return_value=mcp_context):
        result = await tool_fn()

    data = json.loads(result)
    assert data["success"] is True
    assert data["data"] == return_value


@pytest.mark.asyncio
async def test_get_log_by_id_tool_success(mcp_context: MagicMock, mock_mikrus: MagicMock) -> None:
    mock_mikrus.get_log_by_id.return_value = {"id": "5", "task": "test"}

    with patch.object(mcp, "get_context", return_value=mcp_context):
        result = await get_log_by_id_tool("5")

    data = json.loads(result)
    assert data["success"] is True
    assert data["data"]["id"] == "5"


@pytest.mark.asyncio
async def test_assign_domain_tool_success(mcp_context: MagicMock, mock_mikrus: MagicMock) -> None:
    mock_mikrus.assign_domain.return_value = {"domain": "test.mikr.us", "port": "3000"}

    with patch.object(mcp, "get_context", return_value=mcp_context):
        result = await assign_domain_tool("3000", "-")

    data = json.loads(result)
    assert data["success"] is True
    assert data["data"]["domain"] == "test.mikr.us"


# === Mikrus-only tools — wrong server type error ===


@pytest.mark.asyncio
async def test_mikrus_tool_on_ssh_server_returns_error(mcp_context: MagicMock) -> None:
    with patch.object(mcp, "get_context", return_value=mcp_context):
        result = await get_server_info_tool("beta")

    data = json.loads(result)
    assert data["success"] is False
    assert "mikrus" in data["error"].lower()


# === Mikrus-only — client error handling ===


@pytest.mark.asyncio
async def test_mikrus_tool_client_error(mcp_context: MagicMock, mock_mikrus: MagicMock) -> None:
    mock_mikrus.get_server_info.side_effect = RuntimeError("connection failed")

    with patch.object(mcp, "get_context", return_value=mcp_context):
        result = await get_server_info_tool()

    data = json.loads(result)
    assert data["success"] is False
    assert "connection failed" in data["error"]


MIKRUS_ERROR_TOOLS = [
    (list_servers_tool, "list_servers", ()),
    (get_server_stats_tool, "get_server_stats", ()),
    (restart_server_tool, "restart_server", ()),
    (get_logs_tool, "get_logs", ()),
    (boost_server_tool, "boost_server", ()),
    (get_db_info_tool, "get_db_info", ()),
    (get_ports_tool, "get_ports", ()),
    (get_cloud_tool, "get_cloud", ()),
    (get_log_by_id_tool, "get_log_by_id", ("1",)),
    (assign_domain_tool, "assign_domain", ("3000", "-")),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_fn, method_name, args", MIKRUS_ERROR_TOOLS)
async def test_mikrus_tools_error(
    tool_fn: object,
    method_name: str,
    args: tuple,
    mcp_context: MagicMock,
    mock_mikrus: MagicMock,
) -> None:
    mock_method = getattr(mock_mikrus, method_name)
    mock_method.side_effect = RuntimeError("boom")

    with patch.object(mcp, "get_context", return_value=mcp_context):
        result = await tool_fn(*args)

    data = json.loads(result)
    assert data["success"] is False
    assert "boom" in data["error"]


SYSTEM_ERROR_TOOLS = [
    (read_file_tool, "read_file", ("/etc/hosts",)),
    (write_file_tool, "write_file", ("/tmp/x.txt", "data")),
    (manage_service_tool, "manage_service", ("nginx", "status")),
    (analyze_disk_tool, "analyze_disk", ("/",)),
    (check_port_tool, "check_port", ("80",)),
    (manage_process_tool, "manage_process", ("list",)),
    (update_system_tool, "update_system", ()),
    (list_directory_tool, "list_directory", ("/tmp",)),
    (tail_file_tool, "tail_file", ("/var/log/x",)),
    (search_in_files_tool, "search_in_files", ("/etc", "x")),
    (get_memory_info_tool, "get_memory_info", ()),
    (get_network_info_tool, "get_network_info", ()),
    (get_process_tree_tool, "get_process_tree", ()),
    (list_docker_containers_tool, "list_docker_containers", ()),
    (get_docker_logs_tool, "get_docker_logs", ("app",)),
    (get_docker_stats_tool, "get_docker_stats", ()),
    (get_journal_logs_tool, "get_journal_logs", ("ssh",)),
    (find_system_errors_tool, "find_system_errors", ()),
    (search_journal_logs_tool, "search_journal_logs", ("err",)),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_fn, method_name, args", SYSTEM_ERROR_TOOLS)
async def test_system_tools_error(
    tool_fn: object,
    method_name: str,
    args: tuple,
    mcp_context: MagicMock,
    mock_mikrus: MagicMock,
) -> None:
    mock_method = getattr(mock_mikrus, method_name)
    mock_method.side_effect = RuntimeError("boom")

    with patch.object(mcp, "get_context", return_value=mcp_context):
        result = await tool_fn(*args)

    data = json.loads(result)
    assert data["success"] is False
    assert "boom" in data["error"]


# === SSH-compatible tools — success on mikrus server ===


@pytest.mark.asyncio
async def test_execute_command_tool_success(mcp_context: MagicMock, mock_mikrus: MagicMock) -> None:
    mock_mikrus.execute_command.return_value = {"output": "hello", "exit_code": 0}

    with patch.object(mcp, "get_context", return_value=mcp_context):
        result = await execute_command_tool("echo hello")

    data = json.loads(result)
    assert data["success"] is True
    assert data["data"]["output"] == "hello"


@pytest.mark.asyncio
async def test_read_file_tool_success(mcp_context: MagicMock, mock_mikrus: MagicMock) -> None:
    mock_mikrus.read_file.return_value = {"output": "line1\nline2", "exit_code": 0}

    with patch.object(mcp, "get_context", return_value=mcp_context):
        result = await read_file_tool("/etc/hosts")

    data = json.loads(result)
    assert data["success"] is True
    assert "line1" in data["data"]["output"]


@pytest.mark.asyncio
async def test_write_file_tool_success(mcp_context: MagicMock, mock_mikrus: MagicMock) -> None:
    mock_mikrus.write_file.return_value = {"output": "WRITE_OK", "exit_code": 0}

    with patch.object(mcp, "get_context", return_value=mcp_context):
        result = await write_file_tool("/tmp/test.txt", "data")

    data = json.loads(result)
    assert data["success"] is True
    assert "WRITE_OK" in data["data"]["output"]


@pytest.mark.asyncio
async def test_manage_service_tool_success(mcp_context: MagicMock, mock_mikrus: MagicMock) -> None:
    mock_mikrus.manage_service.return_value = {"output": "active", "exit_code": 0}

    with patch.object(mcp, "get_context", return_value=mcp_context):
        result = await manage_service_tool("nginx", "status")

    data = json.loads(result)
    assert data["success"] is True
    assert "active" in data["data"]["output"]


@pytest.mark.asyncio
async def test_analyze_disk_tool_success(mcp_context: MagicMock, mock_mikrus: MagicMock) -> None:
    mock_mikrus.analyze_disk.return_value = {"output": "/dev/sda1 15G", "exit_code": 0}

    with patch.object(mcp, "get_context", return_value=mcp_context):
        result = await analyze_disk_tool("/")

    data = json.loads(result)
    assert data["success"] is True
    assert "sda" in data["data"]["output"]


@pytest.mark.asyncio
async def test_check_port_tool_success(mcp_context: MagicMock, mock_mikrus: MagicMock) -> None:
    mock_mikrus.check_port.return_value = {"output": "LISTEN *:80", "exit_code": 0}

    with patch.object(mcp, "get_context", return_value=mcp_context):
        result = await check_port_tool("80")

    data = json.loads(result)
    assert data["success"] is True
    assert "LISTEN" in data["data"]["output"]


@pytest.mark.asyncio
async def test_manage_process_tool_success(mcp_context: MagicMock, mock_mikrus: MagicMock) -> None:
    mock_mikrus.manage_process.return_value = {"output": "root node", "exit_code": 0}

    with patch.object(mcp, "get_context", return_value=mcp_context):
        result = await manage_process_tool("list")

    data = json.loads(result)
    assert data["success"] is True
    assert "node" in data["data"]["output"]


@pytest.mark.asyncio
async def test_update_system_tool_success(mcp_context: MagicMock, mock_mikrus: MagicMock) -> None:
    mock_mikrus.update_system.return_value = {"output": "0 upgraded", "exit_code": 0}

    with patch.object(mcp, "get_context", return_value=mcp_context):
        result = await update_system_tool()

    data = json.loads(result)
    assert data["success"] is True
    assert "upgraded" in data["data"]["output"]


@pytest.mark.asyncio
async def test_list_directory_tool_success(mcp_context: MagicMock, mock_mikrus: MagicMock) -> None:
    mock_mikrus.list_directory.return_value = {"output": "drwxr-xr-x root /tmp", "exit_code": 0}

    with patch.object(mcp, "get_context", return_value=mcp_context):
        result = await list_directory_tool("/tmp")

    data = json.loads(result)
    assert data["success"] is True
    assert "root" in data["data"]["output"]


@pytest.mark.asyncio
async def test_tail_file_tool_success(mcp_context: MagicMock, mock_mikrus: MagicMock) -> None:
    mock_mikrus.tail_file.return_value = {"output": "last line", "exit_code": 0}

    with patch.object(mcp, "get_context", return_value=mcp_context):
        result = await tail_file_tool("/var/log/syslog", 20)

    data = json.loads(result)
    assert data["success"] is True
    assert "last line" in data["data"]["output"]


@pytest.mark.asyncio
async def test_search_in_files_tool_success(mcp_context: MagicMock, mock_mikrus: MagicMock) -> None:
    mock_mikrus.search_in_files.return_value = {"output": "found", "exit_code": 0}

    with patch.object(mcp, "get_context", return_value=mcp_context):
        result = await search_in_files_tool("/etc", "test")

    data = json.loads(result)
    assert data["success"] is True
    assert "found" in data["data"]["output"]


@pytest.mark.asyncio
async def test_get_memory_info_tool_success(mcp_context: MagicMock, mock_mikrus: MagicMock) -> None:
    mock_mikrus.get_memory_info.return_value = {"output": "Mem: 1G", "exit_code": 0}

    with patch.object(mcp, "get_context", return_value=mcp_context):
        result = await get_memory_info_tool()

    data = json.loads(result)
    assert data["success"] is True
    assert "Mem" in data["data"]["output"]


@pytest.mark.asyncio
async def test_get_network_info_tool_success(mcp_context: MagicMock, mock_mikrus: MagicMock) -> None:
    mock_mikrus.get_network_info.return_value = {"output": "eth0: UP", "exit_code": 0}

    with patch.object(mcp, "get_context", return_value=mcp_context):
        result = await get_network_info_tool()

    data = json.loads(result)
    assert data["success"] is True
    assert "eth0" in data["data"]["output"]


@pytest.mark.asyncio
async def test_get_process_tree_tool_success(mcp_context: MagicMock, mock_mikrus: MagicMock) -> None:
    mock_mikrus.get_process_tree.return_value = {"output": "root 1 init", "exit_code": 0}

    with patch.object(mcp, "get_context", return_value=mcp_context):
        result = await get_process_tree_tool()

    data = json.loads(result)
    assert data["success"] is True
    assert "init" in data["data"]["output"]


@pytest.mark.asyncio
async def test_list_docker_containers_tool_success(
    mcp_context: MagicMock, mock_mikrus: MagicMock
) -> None:
    mock_mikrus.list_docker_containers.return_value = {"containers": [{"Names": "app"}]}

    with patch.object(mcp, "get_context", return_value=mcp_context):
        result = await list_docker_containers_tool()

    data = json.loads(result)
    assert data["success"] is True
    assert data["data"]["containers"][0]["Names"] == "app"


@pytest.mark.asyncio
async def test_get_docker_logs_tool_success(mcp_context: MagicMock, mock_mikrus: MagicMock) -> None:
    mock_mikrus.get_docker_logs.return_value = {"output": "log line", "exit_code": 0}

    with patch.object(mcp, "get_context", return_value=mcp_context):
        result = await get_docker_logs_tool("app", 10)

    data = json.loads(result)
    assert data["success"] is True
    assert "log line" in data["data"]["output"]


@pytest.mark.asyncio
async def test_get_docker_stats_tool_success(mcp_context: MagicMock, mock_mikrus: MagicMock) -> None:
    mock_mikrus.get_docker_stats.return_value = {"containers": [{"CPUPerc": "10%"}]}

    with patch.object(mcp, "get_context", return_value=mcp_context):
        result = await get_docker_stats_tool()

    data = json.loads(result)
    assert data["success"] is True
    assert data["data"]["containers"][0]["CPUPerc"] == "10%"


@pytest.mark.asyncio
async def test_get_journal_logs_tool_success(mcp_context: MagicMock, mock_mikrus: MagicMock) -> None:
    mock_mikrus.get_journal_logs.return_value = {"output": "journal line", "exit_code": 0}

    with patch.object(mcp, "get_context", return_value=mcp_context):
        result = await get_journal_logs_tool("ssh.service", 10)

    data = json.loads(result)
    assert data["success"] is True
    assert "journal line" in data["data"]["output"]


@pytest.mark.asyncio
async def test_find_system_errors_tool_success(mcp_context: MagicMock, mock_mikrus: MagicMock) -> None:
    mock_mikrus.find_system_errors.return_value = {"output": "error found", "exit_code": 0}

    with patch.object(mcp, "get_context", return_value=mcp_context):
        result = await find_system_errors_tool(2)

    data = json.loads(result)
    assert data["success"] is True
    assert "error found" in data["data"]["output"]


@pytest.mark.asyncio
async def test_search_journal_logs_tool_success(
    mcp_context: MagicMock, mock_mikrus: MagicMock
) -> None:
    mock_mikrus.search_journal_logs.return_value = {"output": "matched", "exit_code": 0}

    with patch.object(mcp, "get_context", return_value=mcp_context):
        result = await search_journal_logs_tool("failed", 10)

    data = json.loads(result)
    assert data["success"] is True
    assert "matched" in data["data"]["output"]


# === SSH-compatible tools — success on SSH server ===


@pytest.mark.asyncio
async def test_execute_command_tool_ssh(mcp_context: MagicMock, mock_ssh: MagicMock) -> None:
    mock_ssh.execute_command.return_value = {"output": "hello", "exit_code": 0}

    with patch.object(mcp, "get_context", return_value=mcp_context):
        result = await execute_command_tool("echo hello", "beta")

    data = json.loads(result)
    assert data["success"] is True
    assert data["data"]["output"] == "hello"


# === SSH-compatible — client error handling ===


@pytest.mark.asyncio
async def test_execute_command_tool_error(mcp_context: MagicMock, mock_mikrus: MagicMock) -> None:
    mock_mikrus.execute_command.side_effect = RuntimeError("timeout")

    with patch.object(mcp, "get_context", return_value=mcp_context):
        result = await execute_command_tool("sleep 999")

    data = json.loads(result)
    assert data["success"] is False
    assert "timeout" in data["error"]


# === list_configured_servers tests ===


@pytest.mark.asyncio
async def test_list_configured_servers_tool(mcp_context: MagicMock) -> None:
    with patch.object(mcp, "get_context", return_value=mcp_context):
        result = json.loads(await list_configured_servers_tool())

    assert result["success"] is True
    inner = result["data"]
    assert inner["default_server"] == "alpha"
    assert inner["total_count"] == 2
    assert inner["connected_count"] == 2
    assert inner["failed_count"] == 0
    names = {s["name"] for s in inner["servers"]}
    assert names == {"alpha", "beta"}


@pytest.mark.asyncio
async def test_list_configured_servers_tool_with_failed(mock_mikrus: MagicMock, mock_ssh: MagicMock) -> None:
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {
        "clients": {"alpha": mock_mikrus},
        "default": "alpha",
        "failed": {"gamma": "connection refused"},
    }

    with patch.object(mcp, "get_context", return_value=ctx):
        result = json.loads(await list_configured_servers_tool())

    assert result["success"] is True
    inner = result["data"]
    assert inner["total_count"] == 2
    assert inner["failed_count"] == 1
    gamma = next(s for s in inner["servers"] if s["name"] == "gamma")
    assert gamma["status"] == "failed"
    assert "connection refused" in gamma["error"]


@pytest.mark.asyncio
async def test_list_configured_servers_tool_error() -> None:
    with patch.object(mcp, "get_context", side_effect=RuntimeError("dead")):
        result = json.loads(await list_configured_servers_tool())

    assert result["success"] is False
    assert "dead" in result["error"]
