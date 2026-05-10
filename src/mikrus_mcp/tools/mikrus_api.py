"""Mikr.us API-only tools — internal functions, wrappers, and registration."""

import logging
from typing import Any

from mikrus_mcp.client import MikrusClient
from mikrus_mcp.tools.constants import TOOLS_VERSION
from mikrus_mcp.tools.response import (
    _error_response,
    _error_response_extended,
    _success_response,
    _tool_description,
)

logger = logging.getLogger(__name__)

# --- internal functions (directly testable, no MCP dependency) ---


async def _get_server_info(client: MikrusClient) -> Any:
    if not isinstance(client, MikrusClient):
        raise TypeError("Expected MikrusClient, got %s", type(client).__name__)
    return await client.get_server_info()


async def _list_servers(client: MikrusClient) -> Any:
    if not isinstance(client, MikrusClient):
        raise TypeError("Expected MikrusClient, got %s", type(client).__name__)
    return await client.list_servers()


async def _get_server_stats(client: MikrusClient) -> Any:
    if not isinstance(client, MikrusClient):
        raise TypeError("Expected MikrusClient, got %s", type(client).__name__)
    return await client.get_server_stats()


async def _restart_server(client: MikrusClient) -> Any:
    if not isinstance(client, MikrusClient):
        raise TypeError("Expected MikrusClient, got %s", type(client).__name__)
    return await client.restart_server()


async def _get_logs(client: MikrusClient) -> Any:
    if not isinstance(client, MikrusClient):
        raise TypeError("Expected MikrusClient, got %s", type(client).__name__)
    return await client.get_logs()


async def _get_log_by_id(client: MikrusClient, log_id: str) -> Any:
    if not isinstance(client, MikrusClient):
        raise TypeError("Expected MikrusClient, got %s", type(client).__name__)
    if not log_id:
        raise ValueError("log_id cannot be empty")
    return await client.get_log_by_id(log_id)


async def _boost_server(client: MikrusClient) -> Any:
    if not isinstance(client, MikrusClient):
        raise TypeError("Expected MikrusClient, got %s", type(client).__name__)
    return await client.boost_server()


async def _get_db_info(client: MikrusClient) -> Any:
    if not isinstance(client, MikrusClient):
        raise TypeError("Expected MikrusClient, got %s", type(client).__name__)
    return await client.get_db_info()


async def _get_ports(client: MikrusClient) -> Any:
    if not isinstance(client, MikrusClient):
        raise TypeError("Expected MikrusClient, got %s", type(client).__name__)
    return await client.get_ports()


async def _get_cloud(client: MikrusClient) -> Any:
    if not isinstance(client, MikrusClient):
        raise TypeError("Expected MikrusClient, got %s", type(client).__name__)
    return await client.get_cloud()


async def _assign_domain(client: MikrusClient, port: str, domain: str) -> Any:
    if not isinstance(client, MikrusClient):
        raise TypeError("Expected MikrusClient, got %s", type(client).__name__)
    if not port:
        raise ValueError("port cannot be empty")
    if not domain:
        raise ValueError("domain cannot be empty")
    return await client.assign_domain(port, domain)


# --- tool wrappers ---


async def get_server_info_tool(server: str | None = None) -> str:
    """Retrieves basic information about a mikr.us VPS server.

    Args:
        server: Optional server name as configured in this MCP instance. If omitted, the default server is used.

    Returns:
        JSON string with {"success": True, "data": {...}} containing server_id,
        param_ram, param_disk, expires, pro status or
        {"success": False, "error": "..."} on failure.
    """
    from mikrus_mcp.server import _get_client

    try:
        logger.debug("Tool invoked: get_server_info")
        client = _get_client(server)
        if not isinstance(client, MikrusClient):
            return _error_response(f"Server '{server}' is not a mikrus server")
        result = await _get_server_info(client)
        logger.debug("Tool succeeded: get_server_info")
        return _success_response(result, meta={"tool_version": TOOLS_VERSION})
    except Exception as e:
        logger.debug("Tool failed: get_server_info -- %s", e)
        return _error_response_extended(
            "INTERNAL_ERROR",
            str(e),
            True,
            suggestion="Retry in 5 seconds - the mikr.us API may be temporarily unavailable",
        )


async def list_servers_tool(server: str | None = None) -> str:
    """Lists all VPS servers associated with a mikr.us account.

    Args:
        server: Optional server name as configured in this MCP instance. If omitted, the default server is used.

    Returns:
        JSON string with {"success": True, "data": [...]} containing a list of
        server objects or {"success": False, "error": "..."} on failure.
    """
    from mikrus_mcp.server import _get_client

    try:
        logger.debug("Tool invoked: list_servers")
        client = _get_client(server)
        if not isinstance(client, MikrusClient):
            return _error_response(f"Server '{server}' is not a mikrus server")
        result = await _list_servers(client)
        logger.debug("Tool succeeded: list_servers")
        return _success_response(result, meta={"tool_version": TOOLS_VERSION})
    except Exception as e:
        logger.debug("Tool failed: list_servers -- %s", e)
        return _error_response_extended(
            "API_ERROR",
            str(e),
            True,
            suggestion="Retry in a few seconds - the mikr.us API may be temporarily unavailable",
        )


async def get_server_stats_tool(server: str | None = None) -> str:
    """Retrieves current server resource usage statistics.

    Args:
        server: Optional server name as configured in this MCP instance. If omitted, the default server is used.

    Returns:
        JSON string with {"success": True, "data": {...}} containing ram_used,
        disk_used, uptime, load_average, processes or
        {"success": False, "error": "..."} on failure.
    """
    from mikrus_mcp.server import _get_client

    try:
        logger.debug("Tool invoked: get_server_stats")
        client = _get_client(server)
        if not isinstance(client, MikrusClient):
            return _error_response(f"Server '{server}' is not a mikrus server")
        result = await _get_server_stats(client)
        logger.debug("Tool succeeded: get_server_stats")
        return _success_response(result, meta={"tool_version": TOOLS_VERSION})
    except Exception as e:
        logger.debug("Tool failed: get_server_stats -- %s", e)
        return _error_response_extended(
            "API_ERROR",
            str(e),
            True,
            suggestion="Retry in a few seconds - the mikr.us API may be temporarily unavailable",
        )


async def restart_server_tool(server: str | None = None) -> str:
    """Restarts a mikr.us VPS server.

    Args:
        server: Optional server name as configured in this MCP instance. If omitted, the default server is used.

    Returns:
        JSON string with {"success": True, "data": {...}} containing the restart
        result or {"success": False, "error": "..."} on failure.
    """
    from mikrus_mcp.server import _get_client

    try:
        logger.debug("Tool invoked: restart_server")
        client = _get_client(server)
        if not isinstance(client, MikrusClient):
            return _error_response(f"Server '{server}' is not a mikrus server")
        result = await _restart_server(client)
        logger.debug("Tool succeeded: restart_server")
        return _success_response(result, meta={"tool_version": TOOLS_VERSION})
    except Exception as e:
        logger.debug("Tool failed: restart_server -- %s", e)
        return _error_response_extended(
            "INTERNAL_ERROR",
            str(e),
            True,
            suggestion="The restart may already be in progress. Check server status in 60 seconds",
        )


async def get_logs_tool(server: str | None = None) -> str:
    """Retrieves the last 10 log entries from the server.

    Args:
        server: Optional server name as configured in this MCP instance. If omitted, the default server is used.

    Returns:
        JSON string with {"success": True, "data": [...]} containing a list of
        log entries with id, date, task, result or
        {"success": False, "error": "..."} on failure.
    """
    from mikrus_mcp.server import _get_client

    try:
        logger.debug("Tool invoked: get_logs")
        client = _get_client(server)
        if not isinstance(client, MikrusClient):
            return _error_response(f"Server '{server}' is not a mikrus server")
        result = await _get_logs(client)
        logger.debug("Tool succeeded: get_logs")
        return _success_response(result, meta={"tool_version": TOOLS_VERSION})
    except Exception as e:
        logger.debug("Tool failed: get_logs -- %s", e)
        return _error_response_extended(
            "API_ERROR",
            str(e),
            True,
            suggestion="Retry in a few seconds - the mikr.us API may be temporarily unavailable",
        )


async def get_log_by_id_tool(id: str, server: str | None = None) -> str:
    """Retrieves details of a specific log entry by its ID.

    Args:
        id: Log entry ID to retrieve.
        server: Optional server name as configured in this MCP instance. If omitted, the default server is used.

    Returns:
        JSON string with {"success": True, "data": {...}} containing the log
        entry details or {"success": False, "error": "..."} on failure.
    """
    from mikrus_mcp.server import _get_client

    try:
        logger.debug("Tool invoked: get_log_by_id id=%s", id)
        client = _get_client(server)
        if not isinstance(client, MikrusClient):
            return _error_response(f"Server '{server}' is not a mikrus server")
        result = await _get_log_by_id(client, id)
        logger.debug("Tool succeeded: get_log_by_id")
        return _success_response(result, meta={"tool_version": TOOLS_VERSION})
    except Exception as e:
        logger.debug("Tool failed: get_log_by_id -- %s", e)
        return _error_response_extended(
            "API_ERROR",
            str(e),
            True,
            suggestion="Verify the log entry ID is correct",
        )


async def boost_server_tool(server: str | None = None) -> str:
    """Enables temporary resource boost on the server.

    Args:
        server: Optional server name as configured in this MCP instance. If omitted, the default server is used.

    Returns:
        JSON string with {"success": True, "data": {...}} containing the boost
        result or {"success": False, "error": "..."} on failure.
    """
    from mikrus_mcp.server import _get_client

    try:
        logger.debug("Tool invoked: boost_server")
        client = _get_client(server)
        if not isinstance(client, MikrusClient):
            return _error_response(f"Server '{server}' is not a mikrus server")
        result = await _boost_server(client)
        logger.debug("Tool succeeded: boost_server")
        return _success_response(result, meta={"tool_version": TOOLS_VERSION})
    except Exception as e:
        logger.debug("Tool failed: boost_server -- %s", e)
        return _error_response_extended(
            "API_ERROR",
            str(e),
            False,
            suggestion="Check if boost is already active and retry",
        )


async def get_db_info_tool(server: str | None = None) -> str:
    """Returns database access credentials assigned to the server.

    Args:
        server: Optional server name as configured in this MCP instance. If omitted, the default server is used.

    Returns:
        JSON string with {"success": True, "data": {...}} containing host, port,
        login, password or {"success": False, "error": "..."} on failure.
    """
    from mikrus_mcp.server import _get_client

    try:
        logger.debug("Tool invoked: get_db_info")
        client = _get_client(server)
        if not isinstance(client, MikrusClient):
            return _error_response(f"Server '{server}' is not a mikrus server")
        result = await _get_db_info(client)
        logger.debug("Tool succeeded: get_db_info")
        return _success_response(result, meta={"tool_version": TOOLS_VERSION})
    except Exception as e:
        logger.debug("Tool failed: get_db_info -- %s", e)
        return _error_response_extended(
            "API_ERROR",
            str(e),
            True,
            suggestion="Retry in a few seconds - credentials are cached for 60s",
        )


async def get_ports_tool(server: str | None = None) -> str:
    """Returns the list of TCP/UDP ports assigned to the VPS server.

    Args:
        server: Optional server name as configured in this MCP instance. If omitted, the default server is used.

    Returns:
        JSON string with {"success": True, "data": {...}} containing tcp and udp
        port lists or {"success": False, "error": "..."} on failure.
    """
    from mikrus_mcp.server import _get_client

    try:
        logger.debug("Tool invoked: get_ports")
        client = _get_client(server)
        if not isinstance(client, MikrusClient):
            return _error_response(f"Server '{server}' is not a mikrus server")
        result = await _get_ports(client)
        logger.debug("Tool succeeded: get_ports")
        return _success_response(result, meta={"tool_version": TOOLS_VERSION})
    except Exception as e:
        logger.debug("Tool failed: get_ports -- %s", e)
        return _error_response_extended(
            "API_ERROR",
            str(e),
            True,
            suggestion="Retry in a few seconds - the mikr.us API may be temporarily unavailable",
        )


async def get_cloud_tool(server: str | None = None) -> str:
    """Returns the list of cloud services assigned to the user's account.

    Args:
        server: Optional server name as configured in this MCP instance. If omitted, the default server is used.

    Returns:
        JSON string with {"success": True, "data": {...}} containing services
        list and statistics or {"success": False, "error": "..."} on failure.
    """
    from mikrus_mcp.server import _get_client

    try:
        logger.debug("Tool invoked: get_cloud")
        client = _get_client(server)
        if not isinstance(client, MikrusClient):
            return _error_response(f"Server '{server}' is not a mikrus server")
        result = await _get_cloud(client)
        logger.debug("Tool succeeded: get_cloud")
        return _success_response(result, meta={"tool_version": TOOLS_VERSION})
    except Exception as e:
        logger.debug("Tool failed: get_cloud -- %s", e)
        return _error_response_extended(
            "API_ERROR",
            str(e),
            True,
            suggestion="Retry in a few seconds - the mikr.us API may be temporarily unavailable",
        )


async def assign_domain_tool(port: str, domain: str, server: str | None = None) -> str:
    """Assigns a domain to a specific port on the VPS server.

    Args:
        port: Target port number (e.g. "3000").
        domain: Domain name or "-" for auto-generated subdomain.
        server: Optional server name as configured in this MCP instance. If omitted, the default server is used.

    Returns:
        JSON string with {"success": True, "data": {...}} containing the
        assigned domain and port or {"success": False, "error": "..."} on failure.
    """
    from mikrus_mcp.server import _get_client

    try:
        logger.debug("Tool invoked: assign_domain port=%s domain=%s", port, domain)
        client = _get_client(server)
        if not isinstance(client, MikrusClient):
            return _error_response(f"Server '{server}' is not a mikrus server")
        result = await _assign_domain(client, port, domain)
        logger.debug("Tool succeeded: assign_domain")
        return _success_response(result, meta={"tool_version": TOOLS_VERSION})
    except Exception as e:
        logger.debug("Tool failed: assign_domain -- %s", e)
        return _error_response_extended(
            "API_ERROR",
            str(e),
            False,
            suggestion="Verify the domain format and port number",
        )


# --- registration ---


REGISTERED_MIKRUS_TOOLS: list[tuple[str, str, Any]] = [
    (
        "get_server_info",
        "Retrieves basic information about a mikr.us VPS server: server ID, RAM/disk parameters, expiration date, and whether the PRO plan is active. API-side cache = 60s.",
        get_server_info_tool,
    ),
    (
        "list_servers",
        "Lists all VPS servers associated with a mikr.us account. API-side cache = 60s.",
        list_servers_tool,
    ),
    (
        "get_server_stats",
        "Retrieves current server statistics: RAM usage, disk usage, uptime, load average, and running processes. API-side cache = 60s.",
        get_server_stats_tool,
    ),
    (
        "restart_server",
        "Restarts a mikr.us VPS server. Use when the user explicitly requests a restart. The restart may take a few minutes.",
        restart_server_tool,
    ),
    (
        "get_logs",
        "Retrieves the last 10 log entries from the server (history of tasks performed via the panel). Each entry contains an ID, date, task type and result.",
        get_logs_tool,
    ),
    (
        "get_log_by_id",
        "Retrieves details of a specific log entry by its ID.",
        get_log_by_id_tool,
    ),
    (
        "boost_server",
        "Enables 'amfetamina' (boost) on the server - a temporary, free resource increase (e.g. +512MB RAM for 30 minutes).",
        boost_server_tool,
    ),
    (
        "get_db_info",
        "Returns database access credentials assigned to the server (host, port, login, password). API-side cache = 60s. Do not log or store output.",
        get_db_info_tool,
    ),
    (
        "get_ports",
        "Returns the list of TCP/UDP ports assigned to the VPS server. API-side cache = 60s.",
        get_ports_tool,
    ),
    (
        "get_cloud",
        "Returns the list of cloud services assigned to the user's account along with statistics.",
        get_cloud_tool,
    ),
    (
        "assign_domain",
        "Assigns a domain to a specific port on the VPS server. Use '-' in the domain parameter for an auto-generated subdomain (e.g. your-srv123.mikr.us).",
        assign_domain_tool,
    ),
]


def register_mikrus_tools(mcp: Any) -> None:
    """Register all mikr.us API tools on the given MCP instance."""
    for name, description, handler in REGISTERED_MIKRUS_TOOLS:
        mcp.tool(name=name, description=_tool_description(name, description))(handler)
