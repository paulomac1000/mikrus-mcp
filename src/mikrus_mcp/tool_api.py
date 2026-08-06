"""Typed public MCP tool callables delegating to the invocation kernel."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError

from mikrus_mcp.config import Settings
from mikrus_mcp.kernel import CallerContext, InvocationKernel


@dataclass(frozen=True, slots=True)
class AppContext:
    settings: Settings
    kernel: InvocationKernel


def _caller(ctx: Context[AppContext], approval_token: str | None = None) -> CallerContext:
    settings = ctx.request_context.lifespan_context.settings
    return CallerContext(settings.principal, settings.allowed_scopes, approval_token)


def _require_success(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("success") is True:
        return result
    error = result.get("error") or {}
    code = str(error.get("code", "ERROR"))
    message = str(error.get("message", "operation failed"))
    raise ToolError(f"{code}: {message}")


async def _invoke(
    ctx: Context[AppContext],
    name: str,
    arguments: dict[str, Any],
    approval_token: str | None = None,
) -> dict[str, Any]:
    kernel = ctx.request_context.lifespan_context.kernel
    return _require_success(await kernel.invoke(name, arguments, _caller(ctx, approval_token)))


async def describe_mikrus_capabilities(ctx: Context[AppContext]) -> dict[str, Any]:
    """Return supported and active capability manifests without backend I/O."""
    return await _invoke(ctx, "describe_mikrus_capabilities", {})


async def list_configured_servers(ctx: Context[AppContext]) -> dict[str, Any]:
    """List configured targets and their connection state without selecting a fallback."""
    return await _invoke(ctx, "list_configured_servers", {})


async def get_server_info(ctx: Context[AppContext], server: str | None = None) -> dict[str, Any]:
    """Return basic information for one exact mikr.us target."""
    return await _invoke(ctx, "get_server_info", {"server": server})


async def list_servers(ctx: Context[AppContext], server: str | None = None) -> dict[str, Any]:
    """List VPS resources for the account bound to one exact mikr.us target."""
    return await _invoke(ctx, "list_servers", {"server": server})


async def get_server_stats(ctx: Context[AppContext], server: str | None = None) -> dict[str, Any]:
    """Return current resource statistics for one exact mikr.us target."""
    return await _invoke(ctx, "get_server_stats", {"server": server})


async def restart_server(ctx: Context[AppContext], approval_token: str, server: str | None = None) -> dict[str, Any]:
    """Restart one exact mikr.us target using a one-time server-side approval."""
    return await _invoke(ctx, "restart_server", {"server": server}, approval_token)


async def get_logs(ctx: Context[AppContext], server: str | None = None) -> dict[str, Any]:
    """Return recent control-panel logs for one exact mikr.us target."""
    return await _invoke(ctx, "get_logs", {"server": server})


async def get_log_by_id(log_id: str, ctx: Context[AppContext], server: str | None = None) -> dict[str, Any]:
    """Return one control-panel log identified by its stable log ID."""
    return await _invoke(ctx, "get_log_by_id", {"server": server, "log_id": log_id})


async def boost_server(ctx: Context[AppContext], approval_token: str, server: str | None = None) -> dict[str, Any]:
    """Enable temporary resource boost using a one-time server-side approval."""
    return await _invoke(ctx, "boost_server", {"server": server}, approval_token)


async def get_db_info(ctx: Context[AppContext], server: str | None = None) -> dict[str, Any]:
    """Return minimized database connection information for one authorized target."""
    return await _invoke(ctx, "get_db_info", {"server": server})


async def get_ports(ctx: Context[AppContext], server: str | None = None) -> dict[str, Any]:
    """Return assigned TCP and UDP ports for one exact mikr.us target."""
    return await _invoke(ctx, "get_ports", {"server": server})


async def get_cloud(ctx: Context[AppContext], server: str | None = None) -> dict[str, Any]:
    """Return account cloud services for one authorized mikr.us target."""
    return await _invoke(ctx, "get_cloud", {"server": server})


async def assign_domain(port: str, domain: str, approval_token: str, ctx: Context[AppContext], server: str | None = None) -> dict[str, Any]:
    """Assign a domain to a port using a one-time server-side approval."""
    return await _invoke(ctx, "assign_domain", {"server": server, "port": port, "domain": domain}, approval_token)


async def execute_command(cmd: str, approval_token: str, ctx: Context[AppContext], server: str | None = None) -> dict[str, Any]:
    """Execute one allowlisted command in the disabled-by-default command profile."""
    return await _invoke(ctx, "execute_command", {"server": server, "cmd": cmd}, approval_token)


async def read_file(path: str, ctx: Context[AppContext], server: str | None = None) -> dict[str, Any]:
    """Read a bounded text preview from an authorized absolute path."""
    return await _invoke(ctx, "read_file", {"server": server, "path": path})


async def write_file(path: str, content: str, approval_token: str, ctx: Context[AppContext], server: str | None = None) -> dict[str, Any]:
    """Atomically replace a file under a safe root using one-time approval."""
    return await _invoke(ctx, "write_file", {"server": server, "path": path, "content": content}, approval_token)


async def get_service_status(name: str, ctx: Context[AppContext], server: str | None = None) -> dict[str, Any]:
    """Read systemd status for one validated service name."""
    return await _invoke(ctx, "get_service_status", {"server": server, "name": name})


async def change_service_state(name: str, action: str, approval_token: str, ctx: Context[AppContext], server: str | None = None) -> dict[str, Any]:
    """Change systemd service state using one-time server-side approval."""
    return await _invoke(ctx, "change_service_state", {"server": server, "name": name, "action": action}, approval_token)


async def analyze_disk(ctx: Context[AppContext], path: str = "/", server: str | None = None) -> dict[str, Any]:
    """Return bounded filesystem usage information for an authorized path."""
    return await _invoke(ctx, "analyze_disk", {"server": server, "path": path})


async def check_port(port: str, ctx: Context[AppContext], server: str | None = None) -> dict[str, Any]:
    """Check whether one validated TCP port is listening."""
    return await _invoke(ctx, "check_port", {"server": server, "port": port})


async def list_processes(ctx: Context[AppContext], server: str | None = None) -> dict[str, Any]:
    """Return a bounded process summary for one authorized target."""
    return await _invoke(ctx, "list_processes", {"server": server})


async def terminate_process(target: str, approval_token: str, ctx: Context[AppContext], server: str | None = None) -> dict[str, Any]:
    """Terminate one exact process identifier using one-time approval."""
    return await _invoke(ctx, "terminate_process", {"server": server, "target": target}, approval_token)


async def update_system(ctx: Context[AppContext], approval_token: str, server: str | None = None) -> dict[str, Any]:
    """Run the bounded package update workflow using one-time approval."""
    return await _invoke(ctx, "update_system", {"server": server}, approval_token)


async def list_directory(path: str, ctx: Context[AppContext], server: str | None = None) -> dict[str, Any]:
    """List a bounded directory view for an authorized absolute path."""
    return await _invoke(ctx, "list_directory", {"server": server, "path": path})


async def tail_file(path: str, ctx: Context[AppContext], lines: int = 50, server: str | None = None) -> dict[str, Any]:
    """Return a bounded tail of an authorized text file."""
    return await _invoke(ctx, "tail_file", {"server": server, "path": path, "lines": lines})


async def search_in_files(path: str, pattern: str, ctx: Context[AppContext], server: str | None = None) -> dict[str, Any]:
    """Search files under one authorized path with bounded fixed-string matching."""
    return await _invoke(ctx, "search_in_files", {"server": server, "path": path, "pattern": pattern})


async def get_memory_info(ctx: Context[AppContext], server: str | None = None) -> dict[str, Any]:
    """Return bounded memory usage information for one target."""
    return await _invoke(ctx, "get_memory_info", {"server": server})


async def get_network_info(ctx: Context[AppContext], server: str | None = None) -> dict[str, Any]:
    """Return authorized network interface and listening-port information."""
    return await _invoke(ctx, "get_network_info", {"server": server})


async def get_process_tree(ctx: Context[AppContext], server: str | None = None) -> dict[str, Any]:
    """Return a bounded process tree for one authorized target."""
    return await _invoke(ctx, "get_process_tree", {"server": server})


async def list_docker_containers(ctx: Context[AppContext], server: str | None = None) -> dict[str, Any]:
    """List Docker containers visible to the configured target identity."""
    return await _invoke(ctx, "list_docker_containers", {"server": server})


async def get_docker_logs(container: str, ctx: Context[AppContext], lines: int = 50, server: str | None = None) -> dict[str, Any]:
    """Return a bounded log tail for one validated container name."""
    return await _invoke(ctx, "get_docker_logs", {"server": server, "container": container, "lines": lines})


async def get_docker_stats(ctx: Context[AppContext], server: str | None = None) -> dict[str, Any]:
    """Return one bounded Docker resource snapshot."""
    return await _invoke(ctx, "get_docker_stats", {"server": server})


async def get_journal_logs(unit: str, ctx: Context[AppContext], lines: int = 50, server: str | None = None) -> dict[str, Any]:
    """Return a bounded journal tail for one validated service unit."""
    return await _invoke(ctx, "get_journal_logs", {"server": server, "unit": unit, "lines": lines})


async def find_system_errors(ctx: Context[AppContext], hours: int = 1, server: str | None = None) -> dict[str, Any]:
    """Return bounded error-level journal entries from a validated time window."""
    return await _invoke(ctx, "find_system_errors", {"server": server, "hours": hours})


async def search_journal_logs(term: str, ctx: Context[AppContext], lines: int = 50, server: str | None = None) -> dict[str, Any]:
    """Search a bounded journal window using validated fixed-string input."""
    return await _invoke(ctx, "search_journal_logs", {"server": server, "term": term, "lines": lines})


TOOL_FUNCTIONS: dict[str, Callable[..., Any]] = {
    function.__name__: function
    for function in (
        describe_mikrus_capabilities, list_configured_servers, get_server_info, list_servers,
        get_server_stats, restart_server, get_logs, get_log_by_id, boost_server, get_db_info,
        get_ports, get_cloud, assign_domain, execute_command, read_file, write_file,
        get_service_status, change_service_state, analyze_disk, check_port, list_processes,
        terminate_process, update_system, list_directory, tail_file, search_in_files,
        get_memory_info, get_network_info, get_process_tree, list_docker_containers,
        get_docker_logs, get_docker_stats, get_journal_logs, find_system_errors,
        search_journal_logs,
    )
}
