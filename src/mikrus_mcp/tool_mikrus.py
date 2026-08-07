"""Public MCP tool callables for mikr.us account capabilities."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import Context

from mikrus_mcp.tool_common import AppContext, _invoke


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


async def restart_server(
    ctx: Context[AppContext],
    server: str | None = None,
) -> dict[str, Any]:
    """Restart one exact mikr.us target after a matching server-side approval is loaded."""
    return await _invoke(ctx, "restart_server", {"server": server})


async def get_logs(ctx: Context[AppContext], server: str | None = None) -> dict[str, Any]:
    """Return recent control-panel logs for one exact mikr.us target."""
    return await _invoke(ctx, "get_logs", {"server": server})


async def get_log_by_id(
    log_id: str,
    ctx: Context[AppContext],
    server: str | None = None,
) -> dict[str, Any]:
    """Return one control-panel log identified by its stable log ID."""
    return await _invoke(ctx, "get_log_by_id", {"server": server, "log_id": log_id})


async def boost_server(
    ctx: Context[AppContext],
    server: str | None = None,
) -> dict[str, Any]:
    """Enable temporary resource boost after a matching server-side approval is loaded."""
    return await _invoke(ctx, "boost_server", {"server": server})


async def get_db_info(ctx: Context[AppContext], server: str | None = None) -> dict[str, Any]:
    """Return minimized database connection information for one authorized target."""
    return await _invoke(ctx, "get_db_info", {"server": server})


async def get_ports(ctx: Context[AppContext], server: str | None = None) -> dict[str, Any]:
    """Return assigned TCP and UDP ports for one exact mikr.us target."""
    return await _invoke(ctx, "get_ports", {"server": server})


async def get_cloud(ctx: Context[AppContext], server: str | None = None) -> dict[str, Any]:
    """Return account cloud services for one authorized mikr.us target."""
    return await _invoke(ctx, "get_cloud", {"server": server})


async def assign_domain(
    port: str,
    domain: str,
    ctx: Context[AppContext],
    server: str | None = None,
) -> dict[str, Any]:
    """Assign a domain to a port after a matching server-side approval is loaded."""
    return await _invoke(
        ctx,
        "assign_domain",
        {"server": server, "port": port, "domain": domain},
    )
