"""System management tools shared across mikrus + SSH servers."""

import logging
from typing import Any

from mikrus_mcp.client import MikrusClient, SshClient
from mikrus_mcp.tools.constants import READ_ONLY_SERVICE_ACTIONS, TOOLS_VERSION
from mikrus_mcp.tools.response import (
    _error_response_extended,
    _success_response,
    _tool_description,
)
from mikrus_mcp.validators import check_write_enabled, validate_command

logger = logging.getLogger(__name__)

# --- internal functions (directly testable, no MCP dependency) ---


async def _execute_command(client: MikrusClient | SshClient, cmd: str) -> Any:
    if not isinstance(client, (MikrusClient, SshClient)):
        raise TypeError(f"Expected MikrusClient or SshClient, got {type(client).__name__}")
    return await client.execute_command(cmd)


async def _read_file(client: MikrusClient | SshClient, path: str) -> Any:
    if not isinstance(client, (MikrusClient, SshClient)):
        raise TypeError(f"Expected MikrusClient or SshClient, got {type(client).__name__}")
    return await client.read_file(path)


async def _write_file(client: MikrusClient | SshClient, path: str, content: str) -> Any:
    if not isinstance(client, (MikrusClient, SshClient)):
        raise TypeError(f"Expected MikrusClient or SshClient, got {type(client).__name__}")
    return await client.write_file(path, content)


async def _manage_service(client: MikrusClient | SshClient, name: str, action: str) -> Any:
    if not isinstance(client, (MikrusClient, SshClient)):
        raise TypeError(f"Expected MikrusClient or SshClient, got {type(client).__name__}")
    return await client.manage_service(name, action)


async def _analyze_disk(client: MikrusClient | SshClient, path: str) -> Any:
    if not isinstance(client, (MikrusClient, SshClient)):
        raise TypeError(f"Expected MikrusClient or SshClient, got {type(client).__name__}")
    return await client.analyze_disk(path)


async def _check_port(client: MikrusClient | SshClient, port: str) -> Any:
    if not isinstance(client, (MikrusClient, SshClient)):
        raise TypeError(f"Expected MikrusClient or SshClient, got {type(client).__name__}")
    return await client.check_port(port)


async def _manage_process(client: MikrusClient | SshClient, target: str, action: str) -> Any:
    if not isinstance(client, (MikrusClient, SshClient)):
        raise TypeError(f"Expected MikrusClient or SshClient, got {type(client).__name__}")
    return await client.manage_process(target, action)


async def _update_system(client: MikrusClient | SshClient) -> Any:
    if not isinstance(client, (MikrusClient, SshClient)):
        raise TypeError(f"Expected MikrusClient or SshClient, got {type(client).__name__}")
    return await client.update_system()


async def _list_directory(client: MikrusClient | SshClient, path: str) -> Any:
    if not isinstance(client, (MikrusClient, SshClient)):
        raise TypeError(f"Expected MikrusClient or SshClient, got {type(client).__name__}")
    return await client.list_directory(path)


async def _tail_file(client: MikrusClient | SshClient, path: str, lines: int) -> Any:
    if not isinstance(client, (MikrusClient, SshClient)):
        raise TypeError(f"Expected MikrusClient or SshClient, got {type(client).__name__}")
    return await client.tail_file(path, lines)


async def _search_in_files(client: MikrusClient | SshClient, path: str, pattern: str) -> Any:
    if not isinstance(client, (MikrusClient, SshClient)):
        raise TypeError(f"Expected MikrusClient or SshClient, got {type(client).__name__}")
    return await client.search_in_files(path, pattern)


async def _get_memory_info(client: MikrusClient | SshClient) -> Any:
    if not isinstance(client, (MikrusClient, SshClient)):
        raise TypeError(f"Expected MikrusClient or SshClient, got {type(client).__name__}")
    return await client.get_memory_info()


async def _get_network_info(client: MikrusClient | SshClient) -> Any:
    if not isinstance(client, (MikrusClient, SshClient)):
        raise TypeError(f"Expected MikrusClient or SshClient, got {type(client).__name__}")
    return await client.get_network_info()


async def _get_process_tree(client: MikrusClient | SshClient) -> Any:
    if not isinstance(client, (MikrusClient, SshClient)):
        raise TypeError(f"Expected MikrusClient or SshClient, got {type(client).__name__}")
    return await client.get_process_tree()


# --- tool wrappers ---


async def execute_command_tool(cmd: str, server: str | None = None) -> str:
    """Executes a shell command on the server.

    Args:
        cmd: Shell command to execute. Examples: 'uptime', 'df -h'.
        server: Optional server name as configured in this MCP instance. If omitted, the default server is used.

    Returns:
        JSON string with {"success": True, "data": {...}} containing output and
        exit_code or {"success": False, "error": "..."} on failure.
    """
    from mikrus_mcp.server import _get_client

    try:
        logger.debug("Tool invoked: execute_command cmd=%s", cmd)
        validate_command(cmd)
        check_write_enabled()
        client = _get_client(server)
        result = await _execute_command(client, cmd)
        logger.debug("Tool succeeded: execute_command")
        return _success_response(result, meta={"tool_version": TOOLS_VERSION})
    except Exception as e:
        logger.debug("Tool failed: execute_command — %s", e)
        return _error_response_extended(
            "INTERNAL_ERROR",
            str(e),
            True,
            suggestion="Retry with a simpler command or check server connectivity",
        )


async def read_file_tool(path: str, server: str | None = None) -> str:
    """Reads a text file from the server.

    Args:
        path: Absolute path to the file (e.g. '/etc/hosts').
        server: Optional server name as configured in this MCP instance. If omitted, the default server is used.

    Returns:
        JSON string with {"success": True, "data": {...}} containing file output
        and exit_code or {"success": False, "error": "..."} on failure.
    """
    from mikrus_mcp.server import _get_client

    try:
        logger.debug("Tool invoked: read_file path=%s", path)
        client = _get_client(server)
        result = await _read_file(client, path)
        logger.debug("Tool succeeded: read_file")
        return _success_response(result, meta={"tool_version": TOOLS_VERSION})
    except Exception as e:
        logger.debug("Tool failed: read_file — %s", e)
        return _error_response_extended(
            "INVALID_PARAM",
            str(e),
            False,
            suggestion="Provide an absolute path starting with /, e.g. /etc/hosts",
        )


async def write_file_tool(path: str, content: str, server: str | None = None) -> str:
    """Writes text content to a file on the server.

    Args:
        path: Absolute path to the target file (e.g. '/tmp/config.txt').
        content: Text content to write to the file.
        server: Optional server name as configured in this MCP instance. If omitted, the default server is used.

    Returns:
        JSON string with {"success": True, "data": {...}} containing write result
        or {"success": False, "error": "..."} on failure.
    """
    from mikrus_mcp.server import _get_client

    try:
        logger.debug("Tool invoked: write_file path=%s", path)
        check_write_enabled()
        client = _get_client(server)
        result = await _write_file(client, path, content)
        logger.debug("Tool succeeded: write_file")
        return _success_response(result, meta={"tool_version": TOOLS_VERSION})
    except Exception as e:
        logger.debug("Tool failed: write_file — %s", e)
        return _error_response_extended(
            "INTERNAL_ERROR",
            str(e),
            False,
            suggestion="Check that the target directory exists and is writable",
        )


async def manage_service_tool(name: str, action: str, server: str | None = None) -> str:
    """Manages a systemd service on the server.

    Args:
        name: Service name (e.g. 'nginx', 'docker.service').
        action: Action to perform: status, start, stop, restart, enable,
            disable, is-active, is-enabled.
        server: Optional server name as configured in this MCP instance. If omitted, the default server is used.

    Returns:
        JSON string with {"success": True, "data": {...}} containing service
        status output or {"success": False, "error": "..."} on failure.
    """
    from mikrus_mcp.server import _get_client

    try:
        logger.debug("Tool invoked: manage_service name=%s action=%s", name, action)
        if action not in READ_ONLY_SERVICE_ACTIONS:
            check_write_enabled()
        client = _get_client(server)
        result = await _manage_service(client, name, action)
        logger.debug("Tool succeeded: manage_service")
        return _success_response(result, meta={"tool_version": TOOLS_VERSION})
    except Exception as e:
        logger.debug("Tool failed: manage_service — %s", e)
        return _error_response_extended(
            "INVALID_PARAM",
            str(e),
            False,
            suggestion="Valid actions: status, start, stop, restart, enable, disable, is-active, is-enabled",
        )


async def analyze_disk_tool(path: str = "/", server: str | None = None) -> str:
    """Analyzes disk usage on the server.

    Args:
        path: Starting path for directory size analysis (default: "/").
        server: Optional server name as configured in this MCP instance. If omitted, the default server is used.

    Returns:
        JSON string with {"success": True, "data": {...}} containing df output
        and largest directories list or {"success": False, "error": "..."} on failure.
    """
    from mikrus_mcp.server import _get_client

    try:
        logger.debug("Tool invoked: analyze_disk path=%s", path)
        client = _get_client(server)
        result = await _analyze_disk(client, path)
        logger.debug("Tool succeeded: analyze_disk")
        return _success_response(result, meta={"tool_version": TOOLS_VERSION})
    except Exception as e:
        logger.debug("Tool failed: analyze_disk — %s", e)
        return _error_response_extended(
            "HTTP_ERROR",
            str(e),
            True,
            suggestion="Retry with a different path or check disk health",
        )


async def check_port_tool(port: str, server: str | None = None) -> str:
    """Checks whether a specific TCP port is listening on the server.

    Args:
        port: TCP port number to check (1-65535).
        server: Optional server name as configured in this MCP instance. If omitted, the default server is used.

    Returns:
        JSON string with {"success": True, "data": {...}} containing port status
        and process info or {"success": False, "error": "..."} on failure.
    """
    from mikrus_mcp.server import _get_client

    try:
        logger.debug("Tool invoked: check_port port=%s", port)
        client = _get_client(server)
        result = await _check_port(client, port)
        logger.debug("Tool succeeded: check_port")
        return _success_response(result, meta={"tool_version": TOOLS_VERSION})
    except Exception as e:
        logger.debug("Tool failed: check_port — %s", e)
        return _error_response_extended(
            "HTTP_ERROR",
            str(e),
            True,
            suggestion="Verify the port number is between 1-65535",
        )


async def manage_process_tool(action: str, target: str = "", server: str | None = None) -> str:
    """Lists or kills processes on the server.

    Args:
        action: Either "list" to show top-20 processes or "kill" to terminate.
        target: Process name or PID to kill (required for "kill" action).
        server: Optional server name as configured in this MCP instance. If omitted, the default server is used.

    Returns:
        JSON string with {"success": True, "data": {...}} containing process list
        or kill result or {"success": False, "error": "..."} on failure.
    """
    from mikrus_mcp.server import _get_client

    try:
        logger.debug("Tool invoked: manage_process action=%s target=%s", action, target)
        if action == "kill":
            check_write_enabled()
        client = _get_client(server)
        result = await _manage_process(client, target, action)
        logger.debug("Tool succeeded: manage_process")
        return _success_response(result, meta={"tool_version": TOOLS_VERSION})
    except Exception as e:
        logger.debug("Tool failed: manage_process — %s", e)
        return _error_response_extended(
            "INTERNAL_ERROR",
            str(e),
            False,
            suggestion="Verify the process name or PID is correct",
        )


async def update_system_tool(server: str | None = None) -> str:
    """Runs system updates on the server.

    Args:
        server: Optional server name as configured in this MCP instance. If omitted, the default server is used.

    Returns:
        JSON string with {"success": True, "data": {...}} containing update
        output and exit_code or {"success": False, "error": "..."} on failure.
    """
    from mikrus_mcp.server import _get_client

    try:
        logger.debug("Tool invoked: update_system")
        check_write_enabled()
        client = _get_client(server)
        result = await _update_system(client)
        logger.debug("Tool succeeded: update_system")
        return _success_response(result, meta={"tool_version": TOOLS_VERSION})
    except Exception as e:
        logger.debug("Tool failed: update_system — %s", e)
        return _error_response_extended(
            "INTERNAL_ERROR",
            str(e),
            False,
            suggestion="Check server connectivity, disk space, and apt sources",
        )


async def list_directory_tool(path: str, server: str | None = None) -> str:
    """Lists contents of a directory on the server.

    Args:
        path: Absolute path to the directory (e.g. '/var/log').
        server: Optional server name as configured in this MCP instance. If omitted, the default server is used.

    Returns:
        JSON string with {"success": True, "data": {...}} containing directory
        listing or {"success": False, "error": "..."} on failure.
    """
    from mikrus_mcp.server import _get_client

    try:
        logger.debug("Tool invoked: list_directory path=%s", path)
        client = _get_client(server)
        result = await _list_directory(client, path)
        logger.debug("Tool succeeded: list_directory")
        return _success_response(result, meta={"tool_version": TOOLS_VERSION})
    except Exception as e:
        logger.debug("Tool failed: list_directory — %s", e)
        return _error_response_extended(
            "HTTP_ERROR",
            str(e),
            True,
            suggestion="Provide an absolute path, e.g. /var/log",
        )


async def tail_file_tool(path: str, lines: int = 50, server: str | None = None) -> str:
    """Reads the last N lines from a text file on the server.

    Args:
        path: Absolute path to the file (e.g. '/var/log/syslog').
        lines: Number of lines to read from the end (default: 50, max: 500).
        server: Optional server name as configured in this MCP instance. If omitted, the default server is used.

    Returns:
        JSON string with {"success": True, "data": {...}} containing file
        tail output or {"success": False, "error": "..."} on failure.
    """
    from mikrus_mcp.server import _get_client

    try:
        logger.debug("Tool invoked: tail_file path=%s lines=%d", path, lines)
        client = _get_client(server)
        result = await _tail_file(client, path, lines)
        logger.debug("Tool succeeded: tail_file")
        return _success_response(result, meta={"tool_version": TOOLS_VERSION})
    except Exception as e:
        logger.debug("Tool failed: tail_file — %s", e)
        return _error_response_extended(
            "HTTP_ERROR",
            str(e),
            True,
            suggestion="Check that the file exists and is readable",
        )


async def search_in_files_tool(path: str, pattern: str, server: str | None = None) -> str:
    """Searches for a pattern inside files under a given path.

    Args:
        path: Directory path to search in (e.g. '/etc').
        pattern: Search pattern or keyword.
        server: Optional server name as configured in this MCP instance. If omitted, the default server is used.

    Returns:
        JSON string with {"success": True, "data": {...}} containing grep
        results or {"success": False, "error": "..."} on failure.
    """
    from mikrus_mcp.server import _get_client

    try:
        logger.debug("Tool invoked: search_in_files path=%s pattern=%s", path, pattern)
        client = _get_client(server)
        result = await _search_in_files(client, path, pattern)
        logger.debug("Tool succeeded: search_in_files")
        return _success_response(result, meta={"tool_version": TOOLS_VERSION})
    except Exception as e:
        logger.debug("Tool failed: search_in_files — %s", e)
        return _error_response_extended(
            "HTTP_ERROR",
            str(e),
            True,
            suggestion="Try a simpler search pattern or a different path",
        )


async def get_memory_info_tool(server: str | None = None) -> str:
    """Shows memory usage on the server.

    Args:
        server: Optional server name as configured in this MCP instance. If omitted, the default server is used.

    Returns:
        JSON string with {"success": True, "data": {...}} containing free -h
        output or {"success": False, "error": "..."} on failure.
    """
    from mikrus_mcp.server import _get_client

    try:
        logger.debug("Tool invoked: get_memory_info")
        client = _get_client(server)
        result = await _get_memory_info(client)
        logger.debug("Tool succeeded: get_memory_info")
        return _success_response(result, meta={"tool_version": TOOLS_VERSION})
    except Exception as e:
        logger.debug("Tool failed: get_memory_info — %s", e)
        return _error_response_extended(
            "HTTP_ERROR",
            str(e),
            True,
            suggestion="Retry in a few seconds",
        )


async def get_network_info_tool(server: str | None = None) -> str:
    """Shows network interfaces and listening TCP ports on the server.

    Args:
        server: Optional server name as configured in this MCP instance. If omitted, the default server is used.

    Returns:
        JSON string with {"success": True, "data": {...}} containing ip addr
        and ss -tlnp output or {"success": False, "error": "..."} on failure.
    """
    from mikrus_mcp.server import _get_client

    try:
        logger.debug("Tool invoked: get_network_info")
        client = _get_client(server)
        result = await _get_network_info(client)
        logger.debug("Tool succeeded: get_network_info")
        return _success_response(result, meta={"tool_version": TOOLS_VERSION})
    except Exception as e:
        logger.debug("Tool failed: get_network_info — %s", e)
        return _error_response_extended(
            "HTTP_ERROR",
            str(e),
            True,
            suggestion="Retry in a few seconds",
        )


async def get_process_tree_tool(server: str | None = None) -> str:
    """Shows running processes in a tree view on the server.

    Args:
        server: Optional server name as configured in this MCP instance. If omitted, the default server is used.

    Returns:
        JSON string with {"success": True, "data": {...}} containing process
        tree output or {"success": False, "error": "..."} on failure.
    """
    from mikrus_mcp.server import _get_client

    try:
        logger.debug("Tool invoked: get_process_tree")
        client = _get_client(server)
        result = await _get_process_tree(client)
        logger.debug("Tool succeeded: get_process_tree")
        return _success_response(result, meta={"tool_version": TOOLS_VERSION})
    except Exception as e:
        logger.debug("Tool failed: get_process_tree — %s", e)
        return _error_response_extended(
            "HTTP_ERROR",
            str(e),
            True,
            suggestion="Retry in a few seconds",
        )


# --- registration ---


REGISTERED_SYSTEM_TOOLS: list[tuple[str, str, Any]] = [
    (
        "execute_command",
        "Executes a shell command on the server. API/SSH execution limit is ~60 seconds. Use with caution, especially for commands that modify the system. Examples: 'uptime', 'df -h', 'ls -la /var/log'.",
        execute_command_tool,
    ),
    (
        "read_file",
        "Reads a text file from the server and returns its content (up to 200 lines). Example paths: '/etc/nginx/sites-available/default', '/var/log/syslog'. Do NOT use on binary files.",
        read_file_tool,
    ),
    (
        "write_file",
        "Writes text content to a file on the server. Overwrites the file if it already exists. Content is base64-transferred for safe handling of special characters.",
        write_file_tool,
    ),
    (
        "manage_service",
        "Manages a systemd service on the server. Actions: status, start, stop, restart, enable, disable, is-active, is-enabled. Common services: nginx, apache2, mysql, postgresql, docker, ssh.",
        manage_service_tool,
    ),
    (
        "analyze_disk",
        "Analyzes disk usage on the server. Returns df -h output and a top-20 list of the largest directories by size.",
        analyze_disk_tool,
    ),
    (
        "check_port",
        "Checks whether a specific TCP port is listening on the server and shows which process is using it. Port range: 1-65535.",
        check_port_tool,
    ),
    (
        "manage_process",
        "Lists or kills processes on the server. Action 'list' returns top-20 processes by memory usage. Action 'kill' terminates a process by PID or name (SIGTERM).",
        manage_process_tool,
    ),
    (
        "update_system",
        "Runs system updates on the server. Note: this may restart services and takes time.",
        update_system_tool,
    ),
    (
        "list_directory",
        "Lists contents of a directory on the server (ls -la). Useful for exploring the filesystem.",
        list_directory_tool,
    ),
    (
        "tail_file",
        "Reads the last N lines from a text file. Great for checking recent log entries. Max 500 lines.",
        tail_file_tool,
    ),
    (
        "search_in_files",
        "Searches for a pattern inside files under a given path (grep -r). Useful for finding configuration values or debugging.",
        search_in_files_tool,
    ),
    (
        "get_memory_info",
        "Shows memory usage (free -h). Helpful when diagnosing performance issues.",
        get_memory_info_tool,
    ),
    (
        "get_network_info",
        "Shows network interfaces and listening TCP ports. Useful for checking IP addresses and open services.",
        get_network_info_tool,
    ),
    (
        "get_process_tree",
        "Shows running processes in a tree view (ps auxf). Helps understand which processes spawn others.",
        get_process_tree_tool,
    ),
]


def register_system_tools(mcp: Any) -> None:
    """Register all system management tools on the given MCP instance."""
    for name, description, handler in REGISTERED_SYSTEM_TOOLS:
        mcp.tool(name=name, description=_tool_description(name, description))(handler)
