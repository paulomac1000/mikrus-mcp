"""MCP server implementation — multi-server with stdio and SSE transport."""

import asyncio
import json
import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp.server import FastMCP
from mcp.server.stdio import stdio_server

from mikrus_mcp.client import MikrusClient, SshClient
from mikrus_mcp.config import load_config

logger = logging.getLogger(__name__)

# Module-level lifespan reference — set by app_lifespan, read by REST bridge
_lifespan_context: dict[str, Any] | None = None


def _setup_logging() -> None:
    """Configure stderr logging with level from LOG_LEVEL env var."""
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    """Manage application lifecycle — open one client per configured server.

    Implements graceful degradation: if one server fails to connect,
    the others are still made available.
    """
    config = load_config()
    clients: dict[str, MikrusClient | SshClient] = {}
    failed: dict[str, str] = {}

    for srv_name, srv_cfg in config["servers"].items():
        client: MikrusClient | SshClient
        try:
            if srv_cfg["type"] == "mikrus":
                client = MikrusClient(
                    base_url=srv_cfg["api_url"],
                    api_key=srv_cfg["key"],
                    server_name=srv_cfg["srv"],
                )
            else:
                client = SshClient(
                    host=srv_cfg["host"],
                    user=srv_cfg.get("user", "root"),
                    port=srv_cfg.get("port", 22),
                    ssh_key=srv_cfg.get("ssh_key"),
                    ssh_cert=srv_cfg.get("ssh_cert"),
                    password=srv_cfg.get("password"),
                    sudo_password=srv_cfg.get("sudo_password"),
                    timeout=srv_cfg.get("timeout", 30),
                    verify_host_key=srv_cfg.get("verify_host_key", False),
                    known_hosts_file=srv_cfg.get("known_hosts_file"),
                )
            await client.open()
            clients[srv_name] = client
            logger.info("Connected to %s (%s)", srv_name, srv_cfg["type"])
        except Exception as exc:
            logger.error("Failed to connect to %s: %s", srv_name, exc)
            failed[srv_name] = str(exc)

    if not clients:
        raise RuntimeError(f"No servers available. Failed: {failed}")

    if failed:
        logger.warning(
            "Partial startup: %d/%d servers available. Failed: %s",
            len(clients),
            len(config["servers"]),
            list(failed.keys()),
        )

    effective_default = config["default"]
    if effective_default not in clients:
        effective_default = next(iter(clients.keys()))

    global _lifespan_context
    lifespan_data = {
        "clients": clients,
        "failed": failed,
        "default": effective_default,
    }
    _lifespan_context = lifespan_data
    mcp._lifespan_data = lifespan_data  # type: ignore[attr-defined]  # For REST bridge access

    yield lifespan_data

    mcp._lifespan_data = None  # type: ignore[attr-defined]
    _lifespan_context = None

    for c in clients.values():
        try:
            await c.close()
        except Exception as exc:
            logger.error("Error closing client: %s", exc)


mcp = FastMCP("mikrus-mcp", lifespan=app_lifespan)


def _get_client(server: str | None = None) -> MikrusClient | SshClient:
    """Resolve which client to use for a tool call."""
    ctx = mcp.get_context()
    lifespan: dict[str, Any] = ctx.request_context.lifespan_context
    clients: dict[str, MikrusClient | SshClient] = lifespan["clients"]
    default: str = lifespan["default"]
    name = server or default
    if name not in clients:
        raise ValueError(f"Unknown server: {name}. Available: {sorted(clients.keys())}")
    return clients[name]


def _success_response(data: Any) -> str:
    """Format a successful tool response."""
    return json.dumps({"success": True, "data": data}, indent=2, ensure_ascii=False)


def _error_response(error: str) -> str:
    """Format an error tool response."""
    return json.dumps({"success": False, "error": error}, indent=2, ensure_ascii=False)


# === Test helper ===


async def _call_tool_logic(name: str, args: dict[str, Any], client: Any) -> list[Any]:
    """Directly invoke tool logic for testing (bypasses MCP transport)."""
    from mcp.types import TextContent

    try:
        if name == "get_server_info":
            result = await client.get_server_info()
        elif name == "list_servers":
            result = await client.list_servers()
        elif name == "get_server_stats":
            result = await client.get_server_stats()
        elif name == "restart_server":
            result = await client.restart_server()
        elif name == "get_logs":
            result = await client.get_logs()
        elif name == "get_log_by_id":
            result = await client.get_log_by_id(args["id"])
        elif name == "boost_server":
            result = await client.boost_server()
        elif name == "get_db_info":
            result = await client.get_db_info()
        elif name == "get_ports":
            result = await client.get_ports()
        elif name == "get_cloud":
            result = await client.get_cloud()
        elif name == "assign_domain":
            result = await client.assign_domain(args["port"], args["domain"])
        elif name == "execute_command":
            result = await client.execute_command(args["cmd"])
        elif name == "read_file":
            result = await client.read_file(args["path"])
        elif name == "write_file":
            result = await client.write_file(args["path"], args["content"])
        elif name == "manage_service":
            result = await client.manage_service(args["name"], args["action"])
        elif name == "analyze_disk":
            result = await client.analyze_disk(args.get("path", "/"))
        elif name == "check_port":
            result = await client.check_port(args["port"])
        elif name == "manage_process":
            result = await client.manage_process(args.get("target", ""), args["action"])
        elif name == "update_system":
            result = await client.update_system()
        elif name == "list_directory":
            result = await client.list_directory(args["path"])
        elif name == "tail_file":
            result = await client.tail_file(args["path"], args.get("lines", 50))
        elif name == "search_in_files":
            result = await client.search_in_files(args["path"], args["pattern"])
        elif name == "get_memory_info":
            result = await client.get_memory_info()
        elif name == "get_network_info":
            result = await client.get_network_info()
        elif name == "get_process_tree":
            result = await client.get_process_tree()
        elif name == "list_docker_containers":
            result = await client.list_docker_containers()
        elif name == "get_docker_logs":
            result = await client.get_docker_logs(args["container"], args.get("lines", 50))
        elif name == "get_docker_stats":
            result = await client.get_docker_stats()
        elif name == "get_journal_logs":
            result = await client.get_journal_logs(args["unit"], args.get("lines", 50))
        elif name == "find_system_errors":
            result = await client.find_system_errors(args.get("hours", 1))
        elif name == "search_journal_logs":
            result = await client.search_journal_logs(args["term"], args.get("lines", 50))
        elif name == "list_configured_servers":
            # Handled separately — never reaches here in test helper
            result = {"error": "Use MCP context for list_configured_servers"}
        else:
            return [TextContent(type="text", text=_error_response(f"Unknown tool: {name}"))]

        return [
            TextContent(
                type="text",
                text=_success_response(result),
            )
        ]
    except KeyError as exc:
        return [
            TextContent(
                type="text",
                text=_error_response(f"Missing required parameter: {exc}"),
            )
        ]
    except Exception as exc:
        return [TextContent(type="text", text=_error_response(str(exc)))]


# === Mikrus API tools (mikrus servers only) ===


@mcp.tool(
    name="get_server_info",
    description=(
        "Retrieves basic information about a mikr.us VPS server: server ID, "
        "RAM/disk parameters, expiration date, and whether the PRO plan is "
        "active. API-side cache = 60s."
    ),
)
async def get_server_info_tool(server: str | None = None) -> str:
    """Retrieves basic information about a mikr.us VPS server.

    Args:
        server: Optional server name as configured in this MCP instance.

    Returns:
        JSON string with {"success": True, "data": {...}} containing server_id,
        param_ram, param_disk, expires, pro status or
        {"success": False, "error": "..."} on failure.
    """
    try:
        client = _get_client(server)
        if not isinstance(client, MikrusClient):
            return _error_response(f"Server '{server}' is not a mikrus server")
        result = await client.get_server_info()
        return _success_response(result)
    except Exception as e:
        return _error_response(str(e))


@mcp.tool(
    name="list_servers",
    description=("Lists all VPS servers associated with a mikr.us account. API-side cache = 60s."),
)
async def list_servers_tool(server: str | None = None) -> str:
    """Lists all VPS servers associated with a mikr.us account.

    Args:
        server: Optional server name as configured in this MCP instance.

    Returns:
        JSON string with {"success": True, "data": [...]} containing a list of
        server objects or {"success": False, "error": "..."} on failure.
    """
    try:
        client = _get_client(server)
        if not isinstance(client, MikrusClient):
            return _error_response(f"Server '{server}' is not a mikrus server")
        result = await client.list_servers()
        return _success_response(result)
    except Exception as e:
        return _error_response(str(e))


@mcp.tool(
    name="get_server_stats",
    description=(
        "Retrieves current server statistics: RAM usage, disk usage, uptime, "
        "load average, and running processes. API-side cache = 60s."
    ),
)
async def get_server_stats_tool(server: str | None = None) -> str:
    """Retrieves current server resource usage statistics.

    Args:
        server: Optional server name as configured in this MCP instance.

    Returns:
        JSON string with {"success": True, "data": {...}} containing ram_used,
        disk_used, uptime, load_average, processes or
        {"success": False, "error": "..."} on failure.
    """
    try:
        client = _get_client(server)
        if not isinstance(client, MikrusClient):
            return _error_response(f"Server '{server}' is not a mikrus server")
        result = await client.get_server_stats()
        return _success_response(result)
    except Exception as e:
        return _error_response(str(e))


@mcp.tool(
    name="restart_server",
    description=(
        "Restarts a mikr.us VPS server. Use when the user explicitly requests "
        "a restart. The restart may take a few minutes."
    ),
)
async def restart_server_tool(server: str | None = None) -> str:
    """Restarts a mikr.us VPS server.

    Args:
        server: Optional server name as configured in this MCP instance.

    Returns:
        JSON string with {"success": True, "data": {...}} containing the restart
        result or {"success": False, "error": "..."} on failure.
    """
    try:
        client = _get_client(server)
        if not isinstance(client, MikrusClient):
            return _error_response(f"Server '{server}' is not a mikrus server")
        result = await client.restart_server()
        return _success_response(result)
    except Exception as e:
        return _error_response(str(e))


@mcp.tool(
    name="get_logs",
    description=(
        "Retrieves the last 10 log entries from the server (history of tasks "
        "performed via the panel). Each entry contains an ID, date, task type "
        "and result."
    ),
)
async def get_logs_tool(server: str | None = None) -> str:
    """Retrieves the last 10 log entries from the server.

    Args:
        server: Optional server name as configured in this MCP instance.

    Returns:
        JSON string with {"success": True, "data": [...]} containing a list of
        log entries with id, date, task, result or
        {"success": False, "error": "..."} on failure.
    """
    try:
        client = _get_client(server)
        if not isinstance(client, MikrusClient):
            return _error_response(f"Server '{server}' is not a mikrus server")
        result = await client.get_logs()
        return _success_response(result)
    except Exception as e:
        return _error_response(str(e))


@mcp.tool(
    name="get_log_by_id",
    description="Retrieves details of a specific log entry by its ID.",
)
async def get_log_by_id_tool(id: str, server: str | None = None) -> str:
    """Retrieves details of a specific log entry by its ID.

    Args:
        id: Log entry ID to retrieve.
        server: Optional server name as configured in this MCP instance.

    Returns:
        JSON string with {"success": True, "data": {...}} containing the log
        entry details or {"success": False, "error": "..."} on failure.
    """
    try:
        client = _get_client(server)
        if not isinstance(client, MikrusClient):
            return _error_response(f"Server '{server}' is not a mikrus server")
        result = await client.get_log_by_id(id)
        return _success_response(result)
    except Exception as e:
        return _error_response(str(e))


@mcp.tool(
    name="boost_server",
    description=(
        "Enables 'amfetamina' (boost) on the server — a temporary, free "
        "resource increase (e.g. +512MB RAM for 30 minutes)."
    ),
)
async def boost_server_tool(server: str | None = None) -> str:
    """Enables temporary resource boost on the server.

    Args:
        server: Optional server name as configured in this MCP instance.

    Returns:
        JSON string with {"success": True, "data": {...}} containing the boost
        result or {"success": False, "error": "..."} on failure.
    """
    try:
        client = _get_client(server)
        if not isinstance(client, MikrusClient):
            return _error_response(f"Server '{server}' is not a mikrus server")
        result = await client.boost_server()
        return _success_response(result)
    except Exception as e:
        return _error_response(str(e))


@mcp.tool(
    name="get_db_info",
    description=(
        "[SENSITIVE] Returns database access credentials assigned to the server "
        "(host, port, login, password). API-side cache = 60s. "
        "Do not log or store output."
    ),
)
async def get_db_info_tool(server: str | None = None) -> str:
    """Returns database access credentials assigned to the server.

    Args:
        server: Optional server name as configured in this MCP instance.

    Returns:
        JSON string with {"success": True, "data": {...}} containing host, port,
        login, password or {"success": False, "error": "..."} on failure.
    """
    try:
        client = _get_client(server)
        if not isinstance(client, MikrusClient):
            return _error_response(f"Server '{server}' is not a mikrus server")
        result = await client.get_db_info()
        return _success_response(result)
    except Exception as e:
        return _error_response(str(e))


@mcp.tool(
    name="get_ports",
    description=(
        "Returns the list of TCP/UDP ports assigned to the VPS server. API-side cache = 60s."
    ),
)
async def get_ports_tool(server: str | None = None) -> str:
    """Returns the list of TCP/UDP ports assigned to the VPS server.

    Args:
        server: Optional server name as configured in this MCP instance.

    Returns:
        JSON string with {"success": True, "data": {...}} containing tcp and udp
        port lists or {"success": False, "error": "..."} on failure.
    """
    try:
        client = _get_client(server)
        if not isinstance(client, MikrusClient):
            return _error_response(f"Server '{server}' is not a mikrus server")
        result = await client.get_ports()
        return _success_response(result)
    except Exception as e:
        return _error_response(str(e))


@mcp.tool(
    name="get_cloud",
    description=(
        "Returns the list of cloud services assigned to the user's account along with statistics."
    ),
)
async def get_cloud_tool(server: str | None = None) -> str:
    """Returns the list of cloud services assigned to the user's account.

    Args:
        server: Optional server name as configured in this MCP instance.

    Returns:
        JSON string with {"success": True, "data": {...}} containing services
        list and statistics or {"success": False, "error": "..."} on failure.
    """
    try:
        client = _get_client(server)
        if not isinstance(client, MikrusClient):
            return _error_response(f"Server '{server}' is not a mikrus server")
        result = await client.get_cloud()
        return _success_response(result)
    except Exception as e:
        return _error_response(str(e))


@mcp.tool(
    name="assign_domain",
    description=(
        "Assigns a domain to a specific port on the VPS server. "
        "Use '-' in the domain parameter for an auto-generated subdomain "
        "(e.g. your-srv123.mikr.us)."
    ),
)
async def assign_domain_tool(port: str, domain: str, server: str | None = None) -> str:
    """Assigns a domain to a specific port on the VPS server.

    Args:
        port: Target port number (e.g. "3000").
        domain: Domain name or "-" for auto-generated subdomain.
        server: Optional server name as configured in this MCP instance.

    Returns:
        JSON string with {"success": True, "data": {...}} containing the
        assigned domain and port or {"success": False, "error": "..."} on failure.
    """
    try:
        client = _get_client(server)
        if not isinstance(client, MikrusClient):
            return _error_response(f"Server '{server}' is not a mikrus server")
        result = await client.assign_domain(port, domain)
        return _success_response(result)
    except Exception as e:
        return _error_response(str(e))


@mcp.tool(
    name="list_configured_servers",
    description=(
        "Lists all servers configured in this MCP instance with their types "
        "and connection status. Use this first to discover available servers."
    ),
)
async def list_configured_servers_tool() -> str:
    """Lists all servers configured in this MCP instance.

    Returns:
        JSON string with {"success": True, "data": {...}} containing
        default_server, total_count, connected_count, failed_count, and a
        servers list with name, type, status, is_default per server.
    """
    try:
        ctx = mcp.get_context()
        lifespan: dict[str, Any] = ctx.request_context.lifespan_context
        clients: dict[str, MikrusClient | SshClient] = lifespan["clients"]
        failed: dict[str, str] = lifespan.get("failed", {})
        default: str = lifespan["default"]

        servers = []
        for name, client in clients.items():
            servers.append(
                {
                    "name": name,
                    "type": ("mikrus" if isinstance(client, MikrusClient) else "ssh"),
                    "status": "connected",
                    "is_default": name == default,
                }
            )

        for name, error in failed.items():
            servers.append(
                {
                    "name": name,
                    "type": "unknown",
                    "status": "failed",
                    "error": error,
                    "is_default": False,
                }
            )

        result = {
            "default_server": default,
            "total_count": len(servers),
            "connected_count": len(clients),
            "failed_count": len(failed),
            "servers": servers,
        }
        return _success_response(result)
    except Exception as e:
        return _error_response(str(e))


# === System tools (mikrus and SSH servers) ===


@mcp.tool(
    name="execute_command",
    description=(
        "[DANGEROUS] Executes a shell command on the server. "
        "API/SSH execution limit is ~60 seconds. "
        "Use with caution, especially for commands that modify the system. "
        "Examples: 'uptime', 'df -h', 'ls -la /var/log'."
    ),
)
async def execute_command_tool(cmd: str, server: str | None = None) -> str:
    """Executes a shell command on the server.

    Args:
        cmd: Shell command to execute. Examples: 'uptime', 'df -h'.
        server: Optional server name as configured in this MCP instance.

    Returns:
        JSON string with {"success": True, "data": {...}} containing output and
        exit_code or {"success": False, "error": "..."} on failure.
    """
    try:
        client = _get_client(server)
        result = await client.execute_command(cmd)
        return _success_response(result)
    except Exception as e:
        return _error_response(str(e))


@mcp.tool(
    name="read_file",
    description=(
        "Reads a text file from the server and returns its content "
        "(up to 200 lines). "
        "Example paths: '/etc/nginx/sites-available/default', '/var/log/syslog'. "
        "Do NOT use on binary files."
    ),
)
async def read_file_tool(path: str, server: str | None = None) -> str:
    """Reads a text file from the server.

    Args:
        path: Absolute path to the file (e.g. '/etc/hosts').
        server: Optional server name as configured in this MCP instance.

    Returns:
        JSON string with {"success": True, "data": {...}} containing file output
        and exit_code or {"success": False, "error": "..."} on failure.
    """
    try:
        client = _get_client(server)
        result = await client.read_file(path)
        return _success_response(result)
    except Exception as e:
        return _error_response(str(e))


@mcp.tool(
    name="write_file",
    description=(
        "[WRITE] Writes text content to a file on the server. "
        "Overwrites the file if it already exists. "
        "Content is base64-transferred for safe handling of special characters."
    ),
)
async def write_file_tool(path: str, content: str, server: str | None = None) -> str:
    """Writes text content to a file on the server.

    Args:
        path: Absolute path to the target file (e.g. '/tmp/config.txt').
        content: Text content to write to the file.
        server: Optional server name as configured in this MCP instance.

    Returns:
        JSON string with {"success": True, "data": {...}} containing write result
        or {"success": False, "error": "..."} on failure.
    """
    try:
        client = _get_client(server)
        result = await client.write_file(path, content)
        return _success_response(result)
    except Exception as e:
        return _error_response(str(e))


@mcp.tool(
    name="manage_service",
    description=(
        "[WRITE] Manages a systemd service on the server. "
        "Actions: status, start, stop, restart, enable, disable, "
        "is-active, is-enabled. "
        "Common services: nginx, apache2, mysql, postgresql, docker, ssh."
    ),
)
async def manage_service_tool(name: str, action: str, server: str | None = None) -> str:
    """Manages a systemd service on the server.

    Args:
        name: Service name (e.g. 'nginx', 'docker.service').
        action: Action to perform: status, start, stop, restart, enable,
            disable, is-active, is-enabled.
        server: Optional server name as configured in this MCP instance.

    Returns:
        JSON string with {"success": True, "data": {...}} containing service
        status output or {"success": False, "error": "..."} on failure.
    """
    try:
        client = _get_client(server)
        result = await client.manage_service(name, action)
        return _success_response(result)
    except Exception as e:
        return _error_response(str(e))


@mcp.tool(
    name="analyze_disk",
    description=(
        "Analyzes disk usage on the server. Returns df -h output "
        "and a top-20 list of the largest directories by size."
    ),
)
async def analyze_disk_tool(path: str = "/", server: str | None = None) -> str:
    """Analyzes disk usage on the server.

    Args:
        path: Starting path for directory size analysis (default: "/").
        server: Optional server name as configured in this MCP instance.

    Returns:
        JSON string with {"success": True, "data": {...}} containing df output
        and largest directories list or {"success": False, "error": "..."} on failure.
    """
    try:
        client = _get_client(server)
        result = await client.analyze_disk(path)
        return _success_response(result)
    except Exception as e:
        return _error_response(str(e))


@mcp.tool(
    name="check_port",
    description=(
        "Checks whether a specific TCP port is listening on the server "
        "and shows which process is using it. Port range: 1–65535."
    ),
)
async def check_port_tool(port: str, server: str | None = None) -> str:
    """Checks whether a specific TCP port is listening on the server.

    Args:
        port: TCP port number to check (1–65535).
        server: Optional server name as configured in this MCP instance.

    Returns:
        JSON string with {"success": True, "data": {...}} containing port status
        and process info or {"success": False, "error": "..."} on failure.
    """
    try:
        client = _get_client(server)
        result = await client.check_port(port)
        return _success_response(result)
    except Exception as e:
        return _error_response(str(e))


@mcp.tool(
    name="manage_process",
    description=(
        "[DESTRUCTIVE] Lists or kills processes on the server. "
        "Action 'list' returns top-20 processes by memory usage. "
        "Action 'kill' terminates a process by PID or name (SIGTERM)."
    ),
)
async def manage_process_tool(action: str, target: str = "", server: str | None = None) -> str:
    """Lists or kills processes on the server.

    Args:
        action: Either "list" to show top-20 processes or "kill" to terminate.
        target: Process name or PID to kill (required for "kill" action).
        server: Optional server name as configured in this MCP instance.

    Returns:
        JSON string with {"success": True, "data": {...}} containing process list
        or kill result or {"success": False, "error": "..."} on failure.
    """
    try:
        client = _get_client(server)
        result = await client.manage_process(target, action)
        return _success_response(result)
    except Exception as e:
        return _error_response(str(e))


@mcp.tool(
    name="update_system",
    description=(
        "[WRITE] Runs system updates on the server. Note: this may restart services and takes time."
    ),
)
async def update_system_tool(server: str | None = None) -> str:
    """Runs system updates on the server.

    Args:
        server: Optional server name as configured in this MCP instance.

    Returns:
        JSON string with {"success": True, "data": {...}} containing update
        output and exit_code or {"success": False, "error": "..."} on failure.
    """
    try:
        client = _get_client(server)
        result = await client.update_system()
        return _success_response(result)
    except Exception as e:
        return _error_response(str(e))


@mcp.tool(
    name="list_directory",
    description=(
        "Lists contents of a directory on the server (ls -la). Useful for exploring the filesystem."
    ),
)
async def list_directory_tool(path: str, server: str | None = None) -> str:
    """Lists contents of a directory on the server.

    Args:
        path: Absolute path to the directory (e.g. '/var/log').
        server: Optional server name as configured in this MCP instance.

    Returns:
        JSON string with {"success": True, "data": {...}} containing directory
        listing or {"success": False, "error": "..."} on failure.
    """
    try:
        client = _get_client(server)
        result = await client.list_directory(path)
        return _success_response(result)
    except Exception as e:
        return _error_response(str(e))


@mcp.tool(
    name="tail_file",
    description=(
        "Reads the last N lines from a text file. Great for checking "
        "recent log entries. Max 500 lines."
    ),
)
async def tail_file_tool(path: str, lines: int = 50, server: str | None = None) -> str:
    """Reads the last N lines from a text file on the server.

    Args:
        path: Absolute path to the file (e.g. '/var/log/syslog').
        lines: Number of lines to read from the end (default: 50, max: 500).
        server: Optional server name as configured in this MCP instance.

    Returns:
        JSON string with {"success": True, "data": {...}} containing file
        tail output or {"success": False, "error": "..."} on failure.
    """
    try:
        client = _get_client(server)
        result = await client.tail_file(path, lines)
        return _success_response(result)
    except Exception as e:
        return _error_response(str(e))


@mcp.tool(
    name="search_in_files",
    description=(
        "Searches for a pattern inside files under a given path (grep -r). "
        "Useful for finding configuration values or debugging."
    ),
)
async def search_in_files_tool(path: str, pattern: str, server: str | None = None) -> str:
    """Searches for a pattern inside files under a given path.

    Args:
        path: Directory path to search in (e.g. '/etc').
        pattern: Search pattern or keyword.
        server: Optional server name as configured in this MCP instance.

    Returns:
        JSON string with {"success": True, "data": {...}} containing grep
        results or {"success": False, "error": "..."} on failure.
    """
    try:
        client = _get_client(server)
        result = await client.search_in_files(path, pattern)
        return _success_response(result)
    except Exception as e:
        return _error_response(str(e))


@mcp.tool(
    name="get_memory_info",
    description=("Shows memory usage (free -h). Helpful when diagnosing performance issues."),
)
async def get_memory_info_tool(server: str | None = None) -> str:
    """Shows memory usage on the server.

    Args:
        server: Optional server name as configured in this MCP instance.

    Returns:
        JSON string with {"success": True, "data": {...}} containing free -h
        output or {"success": False, "error": "..."} on failure.
    """
    try:
        client = _get_client(server)
        result = await client.get_memory_info()
        return _success_response(result)
    except Exception as e:
        return _error_response(str(e))


@mcp.tool(
    name="get_network_info",
    description=(
        "Shows network interfaces and listening TCP ports. "
        "Useful for checking IP addresses and open services."
    ),
)
async def get_network_info_tool(server: str | None = None) -> str:
    """Shows network interfaces and listening TCP ports on the server.

    Args:
        server: Optional server name as configured in this MCP instance.

    Returns:
        JSON string with {"success": True, "data": {...}} containing ip addr
        and ss -tlnp output or {"success": False, "error": "..."} on failure.
    """
    try:
        client = _get_client(server)
        result = await client.get_network_info()
        return _success_response(result)
    except Exception as e:
        return _error_response(str(e))


@mcp.tool(
    name="get_process_tree",
    description=(
        "Shows running processes in a tree view (ps auxf). "
        "Helps understand which processes spawn others."
    ),
)
async def get_process_tree_tool(server: str | None = None) -> str:
    """Shows running processes in a tree view on the server.

    Args:
        server: Optional server name as configured in this MCP instance.

    Returns:
        JSON string with {"success": True, "data": {...}} containing process
        tree output or {"success": False, "error": "..."} on failure.
    """
    try:
        client = _get_client(server)
        result = await client.get_process_tree()
        return _success_response(result)
    except Exception as e:
        return _error_response(str(e))


@mcp.tool(
    name="list_docker_containers",
    description=(
        "Lists all Docker containers with status and image. "
        "Requires Docker to be installed and the user to have access."
    ),
)
async def list_docker_containers_tool(server: str | None = None) -> str:
    """Lists all Docker containers on the server.

    Args:
        server: Optional server name as configured in this MCP instance.

    Returns:
        JSON string with {"success": True, "data": {...}} containing containers
        list with status and image or {"success": False, "error": "..."} on failure.
    """
    try:
        client = _get_client(server)
        result = await client.list_docker_containers()
        return _success_response(result)
    except Exception as e:
        return _error_response(str(e))


@mcp.tool(
    name="get_docker_logs",
    description=(
        "Fetches recent logs from a Docker container (docker logs --tail). "
        "Useful for debugging applications running in containers."
    ),
)
async def get_docker_logs_tool(container: str, lines: int = 50, server: str | None = None) -> str:
    """Fetches recent logs from a Docker container.

    Args:
        container: Container name or ID.
        lines: Number of log lines to fetch (default: 50, max: 500).
        server: Optional server name as configured in this MCP instance.

    Returns:
        JSON string with {"success": True, "data": {...}} containing container
        logs or {"success": False, "error": "..."} on failure.
    """
    try:
        client = _get_client(server)
        result = await client.get_docker_logs(container, lines)
        return _success_response(result)
    except Exception as e:
        return _error_response(str(e))


@mcp.tool(
    name="get_docker_stats",
    description=(
        "Shows resource usage stats for Docker containers. "
        "Helps identify which container consumes the most CPU/RAM."
    ),
)
async def get_docker_stats_tool(server: str | None = None) -> str:
    """Shows resource usage stats for Docker containers on the server.

    Args:
        server: Optional server name as configured in this MCP instance.

    Returns:
        JSON string with {"success": True, "data": {...}} containing container
        stats (CPU, RAM) or {"success": False, "error": "..."} on failure.
    """
    try:
        client = _get_client(server)
        result = await client.get_docker_stats()
        return _success_response(result)
    except Exception as e:
        return _error_response(str(e))


@mcp.tool(
    name="get_journal_logs",
    description=(
        "[SENSITIVE] Fetches systemd journal logs for a specific service unit. "
        "Requires systemd and appropriate permissions. "
        "Warning: logs may contain passwords or tokens."
    ),
)
async def get_journal_logs_tool(unit: str, lines: int = 50, server: str | None = None) -> str:
    """Fetches systemd journal logs for a specific service unit.

    Args:
        unit: Systemd service unit name (e.g. 'ssh.service').
        lines: Number of log lines to fetch (default: 50, max: 500).
        server: Optional server name as configured in this MCP instance.

    Returns:
        JSON string with {"success": True, "data": {...}} containing journal
        entries or {"success": False, "error": "..."} on failure.
    """
    try:
        client = _get_client(server)
        result = await client.get_journal_logs(unit, lines)
        return _success_response(result)
    except Exception as e:
        return _error_response(str(e))


@mcp.tool(
    name="find_system_errors",
    description=(
        "Finds error-level entries in the systemd journal from the last N hours. "
        "Great for quick health checks."
    ),
)
async def find_system_errors_tool(hours: int = 1, server: str | None = None) -> str:
    """Finds error-level entries in the systemd journal.

    Args:
        hours: Number of hours to look back (default: 1, max: 24).
        server: Optional server name as configured in this MCP instance.

    Returns:
        JSON string with {"success": True, "data": {...}} containing error-level
        journal entries or {"success": False, "error": "..."} on failure.
    """
    try:
        client = _get_client(server)
        result = await client.find_system_errors(hours)
        return _success_response(result)
    except Exception as e:
        return _error_response(str(e))


@mcp.tool(
    name="search_journal_logs",
    description=(
        "Searches systemd journal logs for a keyword or phrase. "
        "Useful when you know what to look for."
    ),
)
async def search_journal_logs_tool(term: str, lines: int = 50, server: str | None = None) -> str:
    """Searches systemd journal logs for a keyword or phrase.

    Args:
        term: Keyword or phrase to search for (e.g. 'error', 'failed').
        lines: Maximum number of matching entries (default: 50, max: 500).
        server: Optional server name as configured in this MCP instance.

    Returns:
        JSON string with {"success": True, "data": {...}} containing matching
        journal entries or {"success": False, "error": "..."} on failure.
    """
    try:
        client = _get_client(server)
        result = await client.search_journal_logs(term, lines)
        return _success_response(result)
    except Exception as e:
        return _error_response(str(e))


# === Transport runners ===


async def run_stdio() -> None:
    """Run the MCP server over stdio transport."""
    async with stdio_server() as (read_stream, write_stream):
        await mcp._mcp_server.run(
            read_stream,
            write_stream,
            mcp._mcp_server.create_initialization_options(),
        )


def main() -> None:
    """Entry point. Uses SSE transport when MCP_PORT is set, stdio otherwise."""
    _setup_logging()

    port_str = os.getenv("MCP_PORT", "").strip()
    rest_port_str = os.getenv("MCP_REST_PORT", "").strip()

    if port_str:
        host = os.getenv("MCP_HOST", "127.0.0.1")

        if host == "0.0.0.0":  # nosec B104
            logger.critical(
                "SSE transport listening on 0.0.0.0 WITHOUT AUTHENTICATION. "
                "This exposes FULL CONTROL over all configured servers to "
                "ANYONE on the network. Set MCP_HOST=127.0.0.1 or add auth."
            )
            if not os.getenv("MCP_UNSAFE_PUBLIC_ACCESS_CONFIRMED"):
                raise RuntimeError(
                    "Refusing to start on 0.0.0.0 without MCP_UNSAFE_PUBLIC_ACCESS_CONFIRMED=1"
                )

        try:
            port = int(port_str)
            if not 1 <= port <= 65535:
                raise ValueError(f"Port must be 1-65535, got {port}")
        except ValueError as exc:
            raise RuntimeError(f"Invalid MCP_PORT: {port_str}") from exc

        mcp.settings.host = host
        mcp.settings.port = port

        async def _run_sse_with_rest() -> None:
            if rest_port_str:
                try:
                    rest_port = int(rest_port_str)
                    from mikrus_mcp.rest_bridge import run_rest_bridge

                    rest_task = asyncio.create_task(run_rest_bridge(mcp, rest_port))
                    logger.info("REST bridge listening on 127.0.0.1:%d", rest_port)
                except (ValueError, ImportError) as exc:
                    logger.warning("REST bridge not started: %s", exc)
            else:
                rest_task = None

            await mcp.run_sse_async()

            if rest_task:
                rest_task.cancel()
                try:
                    await rest_task
                except asyncio.CancelledError:
                    pass

        logger.info("Starting MCP server on %s:%s (SSE)", host, port)
        asyncio.run(_run_sse_with_rest())
    else:
        if rest_port_str:
            logger.warning("MCP_REST_PORT ignored — REST bridge only available in SSE mode")

        logger.info("Starting MCP server on stdio")
        asyncio.run(run_stdio())


if __name__ == "__main__":
    main()
