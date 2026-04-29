"""MCP server implementation for mikr.us API."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from mikrus_mcp.client import MikrusClient
from mikrus_mcp.config import load_config

logger = logging.getLogger(__name__)


@asynccontextmanager
async def app_lifespan(server: Server) -> AsyncIterator[dict[str, Any]]:
    """Manage application lifecycle."""
    config = load_config()
    client = MikrusClient(
        base_url=config["base_url"],
        api_key=config["api_key"],
        server_name=config["server_name"],
    )
    await client.open()
    try:
        yield {"client": client}
    finally:
        await client.close()


app = Server("mikrus-mcp", lifespan=app_lifespan)

TOOLS: list[Tool] = [
    Tool(
        name="get_server_info",
        description=(
            "Retrieves basic information about the VPS server: server ID, RAM/disk parameters, "
            "expiration date, and whether the PRO plan is active. "
            "Use this tool when the user asks about server configuration or account status. "
            "API-side cache = 60s."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="list_servers",
        description=(
            "Lists all VPS servers associated with the user's account. "
            "Use when the user has more than one server or asks 'what servers do I have'. "
            "API-side cache = 60s."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="get_server_stats",
        description=(
            "Retrieves current server statistics: RAM usage, disk usage, uptime, load average, "
            "and running processes. Use when the user asks about performance, load, disk space, "
            "or memory consumption. API-side cache = 60s."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="execute_command",
        description=(
            "Executes a shell command on the VPS server via the API. "
            "The API execution limit is 60 seconds — longer commands will fail. "
            "Use with caution, especially for commands that modify the system. "
            "Examples: 'uptime', 'df -h', 'ls -la /var/log', 'cat /etc/os-release'."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "cmd": {
                    "type": "string",
                    "description": "Shell command to execute on the server (e.g. 'uptime')",
                }
            },
            "required": ["cmd"],
        },
    ),
    Tool(
        name="restart_server",
        description=(
            "Restarts the VPS server. Use when the user explicitly requests a restart "
            "or when diagnostics indicate a restart is needed (e.g. frozen services, "
            "high load). The restart may take a few minutes."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="get_logs",
        description=(
            "Retrieves the last 10 log entries from the server (history of tasks performed "
            "via the panel). Each entry contains an ID, date, task type (e.g. restart, boost, "
            "snapshot, diag) and result. Use when the user asks about the operation history."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="get_log_by_id",
        description=(
            "Retrieves details of a specific log entry by its ID. "
            "Use when the user wants to see the full result of a single operation "
            "(e.g. 'show log with ID 10472')."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "Log entry identifier (e.g. '10472')",
                }
            },
            "required": ["id"],
        },
    ),
    Tool(
        name="boost_server",
        description=(
            "Enables 'amfetamina' (boost) on the server — a temporary, free resource increase "
            "(e.g. +512MB RAM for 30 minutes). Use when the server experiences a temporary load "
            "peak, a backup is running, or the user needs more memory for a short time."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="get_db_info",
        description=(
            "Returns database access credentials assigned to the server "
            "(host, port, login, password). Use when the user asks about database "
            "connection, MySQL/PostgreSQL password, or DB configuration. "
            "API-side cache = 60s. Warning: sensitive data — return only to the user, "
            "do not log."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="get_ports",
        description=(
            "Returns the list of TCP/UDP ports assigned to the VPS server. "
            "Use when the user asks which ports are available, whether a specific "
            "port can be used, or is configuring firewall/network services. "
            "API-side cache = 60s."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="get_cloud",
        description=(
            "Returns the list of cloud services assigned to the user's account "
            "along with statistics. Use when the user asks about additional cloud "
            "services, storage, or related resources."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="assign_domain",
        description=(
            "Assigns a domain to a specific port on the VPS server. Use when the "
            "user wants to expose a service under a domain or subdomain. If the user "
            "does not provide their own domain, pass '-' in the domain parameter — "
            "the mikr.us system will auto-generate a subdomain (e.g. your-srv123.mikr.us). "
            "Example ports: '80', '8080', '3000'."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "port": {
                    "type": "string",
                    "description": "Server port number to expose under the domain (e.g. '8080')",
                },
                "domain": {
                    "type": "string",
                    "description": (
                        "Domain name to assign (e.g. 'my-app.pl'). "
                        "Use '-' to let the system auto-assign a mikr.us subdomain."
                    ),
                },
            },
            "required": ["port", "domain"],
        },
    ),
    Tool(
        name="read_file",
        description=(
            "Reads a text file from the VPS server and returns its content (up to 200 lines). "
            "Use when you need to inspect configuration files, logs, or any text file "
            "on the server. Example paths: '/etc/nginx/sites-available/default', "
            "'/var/log/myapp.log', '/home/user/.env'. "
            "Warning: do NOT use on binary files."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the file on the server (e.g. '/etc/hosts')",
                }
            },
            "required": ["path"],
        },
    ),
    Tool(
        name="write_file",
        description=(
            "Writes text content to a file on the VPS server. "
            "Overwrites the file if it already exists. "
            "Use to create or update configuration files, deploy small scripts, "
            "or manage application settings. "
            "Content is base64-transferred for safe handling of special characters. "
            "Example: write an nginx config, update .env variables, create a docker-compose.yml."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Absolute path to the file on the server "
                        "(e.g. '/etc/nginx/nginx.conf')"
                    ),
                },
                "content": {
                    "type": "string",
                    "description": "Text content to write to the file",
                },
            },
            "required": ["path", "content"],
        },
    ),
    Tool(
        name="manage_service",
        description=(
            "Manages a systemd service on the VPS server. "
            "Supported actions: status (check if running), start, stop, restart, "
            "enable (auto-start on boot), disable, is-active, is-enabled. "
            "Common services: nginx, apache2, mysql, postgresql, docker, ssh. "
            "Use when the user asks 'is nginx running?', 'start mysql', "
            "'restart docker', or needs to enable a service on boot."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Systemd service name (e.g. 'nginx', 'mysql', 'docker')",
                },
                "action": {
                    "type": "string",
                    "description": (
                        "Action: status, start, stop, restart, "
                        "enable, disable, is-active, is-enabled"
                    ),
                },
            },
            "required": ["name", "action"],
        },
    ),
    Tool(
        name="analyze_disk",
        description=(
            "Analyzes disk usage on the VPS server. Returns df -h output "
            "and a top-20 list of the largest directories (sorted by size). "
            "Use when the user asks about disk space, 'why is my disk full?', "
            "or wants to find large files/directories consuming storage. "
            "Mikr.us servers typically have limited disk (e.g. 15GB)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to analyze (default: '/'). Must be absolute.",
                }
            },
        },
    ),
    Tool(
        name="check_port",
        description=(
            "Checks whether a specific TCP port is open (listening) on the VPS server "
            "and shows which process is using it. "
            "Use when debugging connectivity issues: 'is port 3000 open?', "
            "'why can't I access my app?', 'what's using port 80?'. "
            "Port range: 1–65535."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "port": {
                    "type": "string",
                    "description": "TCP port number to check (e.g. '3000', '80', '443')",
                }
            },
            "required": ["port"],
        },
    ),
    Tool(
        name="manage_process",
        description=(
            "Lists or kills processes on the VPS server. "
            "Action 'list' returns the top-20 processes by memory usage (ps aux). "
            "Action 'kill' terminates a process by PID or name (uses SIGTERM, graceful shutdown). "
            "Use when the user asks 'what's using all the RAM?', 'kill the stuck node process', "
            "or needs to stop a runaway service."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "PID or process name to kill (only required for 'kill' action)",
                },
                "action": {
                    "type": "string",
                    "description": (
                        "Action: 'list' (show top processes) "
                        "or 'kill' (terminate by PID/name)"
                    ),
                },
            },
            "required": ["action"],
        },
    ),
    Tool(
        name="update_system",
        description=(
            "Runs system updates on the VPS server (apt update && apt upgrade -y). "
            "Use when the user asks to update the system, install security patches, "
            "or upgrade packages. Note: this may restart services and takes time. "
            "API timeout is 65 seconds — large upgrades may exceed this limit."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
]


@app.list_tools()  # type: ignore[untyped-decorator, no-untyped-call]
async def list_tools() -> list[Tool]:
    """List available tools."""
    return TOOLS


async def _call_tool_logic(
    name: str, arguments: dict[str, Any], client: MikrusClient
) -> list[TextContent]:
    """Core tool logic (extracted for testability)."""
    try:
        if name == "get_server_info":
            result = await client.get_server_info()
        elif name == "list_servers":
            result = await client.list_servers()
        elif name == "get_server_stats":
            result = await client.get_server_stats()
        elif name == "execute_command":
            cmd = arguments.get("cmd", "")
            if not cmd or not isinstance(cmd, str):
                raise ValueError("Parameter 'cmd' is required and must be a non-empty string")
            result = await client.execute_command(cmd)
        elif name == "restart_server":
            result = await client.restart_server()
        elif name == "get_logs":
            result = await client.get_logs()
        elif name == "get_log_by_id":
            log_id = arguments.get("id", "")
            if not log_id or not isinstance(log_id, str):
                raise ValueError("Parameter 'id' is required and must be a non-empty string")
            result = await client.get_log_by_id(log_id)
        elif name == "boost_server":
            result = await client.boost_server()
        elif name == "get_db_info":
            result = await client.get_db_info()
        elif name == "get_ports":
            result = await client.get_ports()
        elif name == "get_cloud":
            result = await client.get_cloud()
        elif name == "assign_domain":
            port = arguments.get("port", "")
            domain = arguments.get("domain", "")
            if not port or not isinstance(port, str):
                raise ValueError("Parameter 'port' is required and must be a non-empty string")
            if not isinstance(domain, str):
                raise ValueError("Parameter 'domain' is required and must be a string")
            result = await client.assign_domain(port, domain)
        elif name == "read_file":
            path = arguments.get("path", "")
            if not path or not isinstance(path, str):
                raise ValueError("Parameter 'path' is required and must be a non-empty string")
            result = await client.read_file(path)
        elif name == "write_file":
            path = arguments.get("path", "")
            content = arguments.get("content", "")
            if not path or not isinstance(path, str):
                raise ValueError("Parameter 'path' is required and must be a non-empty string")
            if not isinstance(content, str):
                raise ValueError("Parameter 'content' is required and must be a string")
            result = await client.write_file(path, content)
        elif name == "manage_service":
            name = arguments.get("name", "")
            action = arguments.get("action", "")
            if not name or not isinstance(name, str):
                raise ValueError("Parameter 'name' is required and must be a non-empty string")
            if not action or not isinstance(action, str):
                raise ValueError("Parameter 'action' is required and must be a non-empty string")
            result = await client.manage_service(name, action)
        elif name == "analyze_disk":
            path = arguments.get("path", "/")
            if not isinstance(path, str):
                raise ValueError("Parameter 'path' must be a string")
            result = await client.analyze_disk(path)
        elif name == "check_port":
            port = arguments.get("port", "")
            if not port or not isinstance(port, str):
                raise ValueError("Parameter 'port' is required and must be a non-empty string")
            result = await client.check_port(port)
        elif name == "manage_process":
            target = arguments.get("target", "")
            action = arguments.get("action", "")
            if not action or not isinstance(action, str):
                raise ValueError("Parameter 'action' is required and must be a non-empty string")
            if not isinstance(target, str):
                raise ValueError("Parameter 'target' must be a string")
            result = await client.manage_process(target, action)
        elif name == "update_system":
            result = await client.update_system()
        else:
            raise ValueError(f"Unknown tool: {name}")
    except Exception as exc:
        logger.error("Tool %s failed: %s", name, exc)
        return [TextContent(type="text", text=f"Error: {exc}")]

    return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]


@app.call_tool()  # type: ignore[untyped-decorator]
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Call a tool."""
    ctx = app.request_context
    client: MikrusClient = ctx.lifespan_context["client"]
    return await _call_tool_logic(name, arguments, client)


async def run_server() -> None:
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )


def main() -> None:
    """Entry point for the MCP server."""
    asyncio.run(run_server())


if __name__ == "__main__":
    main()
