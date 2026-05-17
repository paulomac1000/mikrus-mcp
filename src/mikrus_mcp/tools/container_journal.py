"""Container and journal tools shared across mikrus + SSH servers."""

import logging
from typing import Any

from mikrus_mcp.client import MikrusClient, SshClient
from mikrus_mcp.tools.constants import TOOLS_VERSION
from mikrus_mcp.tools.response import _error_response_extended, _success_response, _tool_description

logger = logging.getLogger(__name__)

# --- internal functions (directly testable, no MCP dependency) ---


async def _list_docker_containers(client: MikrusClient | SshClient) -> Any:
    if not isinstance(client, (MikrusClient, SshClient)):
        raise TypeError(f"Expected MikrusClient or SshClient, got {type(client).__name__}")
    return await client.list_docker_containers()


async def _get_docker_logs(client: MikrusClient | SshClient, container: str, lines: int) -> Any:
    if not isinstance(client, (MikrusClient, SshClient)):
        raise TypeError(f"Expected MikrusClient or SshClient, got {type(client).__name__}")
    return await client.get_docker_logs(container, lines)


async def _get_docker_stats(client: MikrusClient | SshClient) -> Any:
    if not isinstance(client, (MikrusClient, SshClient)):
        raise TypeError(f"Expected MikrusClient or SshClient, got {type(client).__name__}")
    return await client.get_docker_stats()


async def _get_journal_logs(client: MikrusClient | SshClient, unit: str, lines: int) -> Any:
    if not isinstance(client, (MikrusClient, SshClient)):
        raise TypeError(f"Expected MikrusClient or SshClient, got {type(client).__name__}")
    return await client.get_journal_logs(unit, lines)


async def _find_system_errors(client: MikrusClient | SshClient, hours: int) -> Any:
    if not isinstance(client, (MikrusClient, SshClient)):
        raise TypeError(f"Expected MikrusClient or SshClient, got {type(client).__name__}")
    return await client.find_system_errors(hours)


async def _search_journal_logs(client: MikrusClient | SshClient, term: str, lines: int) -> Any:
    if not isinstance(client, (MikrusClient, SshClient)):
        raise TypeError(f"Expected MikrusClient or SshClient, got {type(client).__name__}")
    return await client.search_journal_logs(term, lines)


# --- tool wrappers ---


async def list_docker_containers_tool(server: str | None = None) -> str:
    """Lists all Docker containers on the server.

    Args:
        server: Optional server name as configured in this MCP instance. If omitted, the default server is used.

    Returns:
        JSON string with {"success": True, "data": {...}} containing containers
        list with status and image or {"success": False, "error": "..."} on failure.
    """
    from mikrus_mcp.server import _get_client

    try:
        logger.debug("Tool invoked: list_docker_containers")
        client = _get_client(server)
        result = await _list_docker_containers(client)
        logger.debug("Tool succeeded: list_docker_containers")
        return _success_response(result, meta={"tool_version": TOOLS_VERSION})
    except Exception as e:
        logger.debug("Tool failed: list_docker_containers — %s", e)
        return _error_response_extended(
            "HTTP_ERROR",
            str(e),
            True,
            suggestion="Verify Docker is installed and running on the server",
        )


async def get_docker_logs_tool(container: str, lines: int = 50, server: str | None = None) -> str:
    """Fetches recent logs from a Docker container.

    Args:
        container: Container name or ID.
        lines: Number of log lines to fetch (default: 50, max: 500).
        server: Optional server name as configured in this MCP instance. If omitted, the default server is used.

    Returns:
        JSON string with {"success": True, "data": {...}} containing container
        logs or {"success": False, "error": "..."} on failure.
    """
    from mikrus_mcp.server import _get_client

    try:
        logger.debug("Tool invoked: get_docker_logs container=%s lines=%d", container, lines)
        client = _get_client(server)
        result = await _get_docker_logs(client, container, lines)
        logger.debug("Tool succeeded: get_docker_logs")
        return _success_response(result, meta={"tool_version": TOOLS_VERSION})
    except Exception as e:
        logger.debug("Tool failed: get_docker_logs — %s", e)
        return _error_response_extended(
            "HTTP_ERROR",
            str(e),
            True,
            suggestion="Verify the container name is correct",
        )


async def get_docker_stats_tool(server: str | None = None) -> str:
    """Shows resource usage stats for Docker containers on the server.

    Args:
        server: Optional server name as configured in this MCP instance. If omitted, the default server is used.

    Returns:
        JSON string with {"success": True, "data": {...}} containing container
        stats (CPU, RAM) or {"success": False, "error": "..."} on failure.
    """
    from mikrus_mcp.server import _get_client

    try:
        logger.debug("Tool invoked: get_docker_stats")
        client = _get_client(server)
        result = await _get_docker_stats(client)
        logger.debug("Tool succeeded: get_docker_stats")
        return _success_response(result, meta={"tool_version": TOOLS_VERSION})
    except Exception as e:
        logger.debug("Tool failed: get_docker_stats — %s", e)
        return _error_response_extended(
            "HTTP_ERROR",
            str(e),
            True,
            suggestion="Verify Docker is installed and running on the server",
        )


async def get_journal_logs_tool(unit: str, lines: int = 50, server: str | None = None) -> str:
    """Fetches systemd journal logs for a specific service unit.

    Args:
        unit: Systemd service unit name (e.g. 'ssh.service').
        lines: Number of log lines to fetch (default: 50, max: 500).
        server: Optional server name as configured in this MCP instance. If omitted, the default server is used.

    Returns:
        JSON string with {"success": True, "data": {...}} containing journal
        entries or {"success": False, "error": "..."} on failure.
    """
    from mikrus_mcp.server import _get_client

    try:
        logger.debug("Tool invoked: get_journal_logs unit=%s lines=%d", unit, lines)
        client = _get_client(server)
        result = await _get_journal_logs(client, unit, lines)
        logger.debug("Tool succeeded: get_journal_logs")
        return _success_response(result, meta={"tool_version": TOOLS_VERSION})
    except Exception as e:
        logger.debug("Tool failed: get_journal_logs — %s", e)
        return _error_response_extended(
            "HTTP_ERROR",
            str(e),
            True,
            suggestion="The user may need sudo access. Check that sudo_password is configured for SSH servers",
        )


async def find_system_errors_tool(hours: int = 1, server: str | None = None) -> str:
    """Finds error-level entries in the systemd journal.

    Args:
        hours: Number of hours to look back (default: 1, max: 24).
        server: Optional server name as configured in this MCP instance. If omitted, the default server is used.

    Returns:
        JSON string with {"success": True, "data": {...}} containing error-level
        journal entries or {"success": False, "error": "..."} on failure.
    """
    from mikrus_mcp.server import _get_client

    try:
        logger.debug("Tool invoked: find_system_errors hours=%d", hours)
        client = _get_client(server)
        result = await _find_system_errors(client, hours)
        logger.debug("Tool succeeded: find_system_errors")
        return _success_response(result, meta={"tool_version": TOOLS_VERSION})
    except Exception as e:
        logger.debug("Tool failed: find_system_errors — %s", e)
        return _error_response_extended(
            "HTTP_ERROR",
            str(e),
            True,
            suggestion="Retry with fewer hours or check server journal configuration",
        )


async def search_journal_logs_tool(term: str, lines: int = 50, server: str | None = None) -> str:
    """Searches systemd journal logs for a keyword or phrase.

    Args:
        term: Keyword or phrase to search for (e.g. 'error', 'failed').
        lines: Maximum number of matching entries (default: 50, max: 500).
        server: Optional server name as configured in this MCP instance. If omitted, the default server is used.

    Returns:
        JSON string with {"success": True, "data": {...}} containing matching
        journal entries or {"success": False, "error": "..."} on failure.
    """
    from mikrus_mcp.server import _get_client

    try:
        logger.debug("Tool invoked: search_journal_logs term=%s lines=%d", term, lines)
        client = _get_client(server)
        result = await _search_journal_logs(client, term, lines)
        logger.debug("Tool succeeded: search_journal_logs")
        return _success_response(result, meta={"tool_version": TOOLS_VERSION})
    except Exception as e:
        logger.debug("Tool failed: search_journal_logs — %s", e)
        return _error_response_extended(
            "HTTP_ERROR",
            str(e),
            True,
            suggestion="Try a different search term",
        )


# --- registration ---


REGISTERED_CONTAINER_JOURNAL_TOOLS: list[tuple[str, str, Any]] = [
    (
        "list_docker_containers",
        "Lists all Docker containers with status and image. Requires Docker to be installed and the user to have access.",
        list_docker_containers_tool,
    ),
    (
        "get_docker_logs",
        "Fetches recent logs from a Docker container (docker logs --tail). Useful for debugging applications running in containers.",
        get_docker_logs_tool,
    ),
    (
        "get_docker_stats",
        "Shows resource usage stats for Docker containers. Helps identify which container consumes the most CPU/RAM.",
        get_docker_stats_tool,
    ),
    (
        "get_journal_logs",
        "Fetches systemd journal logs for a specific service unit. Requires systemd and appropriate permissions. Warning: logs may contain passwords or tokens.",
        get_journal_logs_tool,
    ),
    (
        "find_system_errors",
        "Finds error-level entries in the systemd journal from the last N hours. Great for quick health checks.",
        find_system_errors_tool,
    ),
    (
        "search_journal_logs",
        "Searches systemd journal logs for a keyword or phrase. Useful when you know what to look for.",
        search_journal_logs_tool,
    ),
]


def register_container_journal_tools(mcp: Any) -> None:
    """Register all container and journal tools on the given MCP instance."""
    for name, description, handler in REGISTERED_CONTAINER_JOURNAL_TOOLS:
        mcp.tool(name=name, description=_tool_description(name, description))(handler)
