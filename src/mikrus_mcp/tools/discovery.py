"""Discovery tool — lists configured servers."""

import logging
from typing import Any

from mikrus_mcp.client import MikrusClient, SshClient
from mikrus_mcp.tools.constants import TOOLS_VERSION
from mikrus_mcp.tools.response import _error_response_extended, _success_response, _tool_description

logger = logging.getLogger(__name__)


def _list_configured_servers_internal(
    clients: dict[str, MikrusClient | SshClient],
    failed: dict[str, str],
    default: str,
) -> dict[str, Any]:
    """Build the server listing from lifespan client data."""
    servers = []
    for name, client in clients.items():
        servers.append(
            {
                "name": name,
                "type": "mikrus" if isinstance(client, MikrusClient) else "ssh",
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
    return {
        "default_server": default,
        "total_count": len(servers),
        "connected_count": len(clients),
        "failed_count": len(failed),
        "servers": servers,
    }


async def list_configured_servers_tool() -> str:
    """Lists all servers configured in this MCP instance.

    Returns:
        JSON string with {"success": True, "data": {...}} containing
        default_server, total_count, connected_count, failed_count, and a
        servers list with name, type, status, is_default per server.
    """
    from mikrus_mcp.server import mcp

    try:
        logger.debug("Tool invoked: list_configured_servers")
        ctx = mcp.get_context()
        lifespan: dict[str, Any] = ctx.request_context.lifespan_context
        clients: dict[str, MikrusClient | SshClient] = lifespan["clients"]
        failed: dict[str, str] = lifespan.get("failed", {})
        default: str = lifespan["default"]

        result = _list_configured_servers_internal(clients, failed, default)
        logger.debug("Tool succeeded: list_configured_servers")
        return _success_response(result, meta={"tool_version": TOOLS_VERSION})
    except Exception as e:
        logger.debug("Tool failed: list_configured_servers — %s", e)
        return _error_response_extended(
            "INTERNAL_ERROR",
            str(e),
            True,
            suggestion="Ensure the server started successfully with at least one connected server",
        )


def register_discovery_tools(mcp: Any) -> None:
    """Register discovery tools on the given MCP instance."""
    mcp.tool(
        name="list_configured_servers",
        description=_tool_description(
            "list_configured_servers",
            "Lists all servers configured in this MCP instance with their types and connection status. Use this first to discover available servers.",
        ),
    )(list_configured_servers_tool)
