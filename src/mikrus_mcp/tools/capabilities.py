"""Capability introspection tool.

Exposes the full tool catalog with capability manifests over the MCP
transport itself. The REST endpoint GET /api/tools/{name}/manifest is
unreachable for an agent connected over pure MCP/SSE; this tool closes
that gap (mcp-server-standards.md, rule 2b, L3+).
"""

import logging
from typing import Any

from mikrus_mcp.tools.constants import CAPABILITIES_SCHEMA_VERSION, TOOL_MANIFESTS, TOOLS_VERSION
from mikrus_mcp.tools.response import _error_response_extended, _success_response, _tool_description

logger = logging.getLogger(__name__)


def _do_describe_mikrus_capabilities() -> dict[str, Any]:
    """Build the capability catalog. Zero I/O — reads from in-memory TOOL_MANIFESTS."""
    return {
        "schema_version": CAPABILITIES_SCHEMA_VERSION,
        "server": "mikrus-mcp",
        "tools_version": TOOLS_VERSION,
        "transports": ["stdio", "sse"],
        "tool_count": len(TOOL_MANIFESTS),
        "tools": list(TOOL_MANIFESTS.values()),
    }


async def describe_mikrus_capabilities_tool() -> str:
    """Returns the full tool catalog with capability manifests, supported transports, and schema version.

    Returns:
        JSON string with {"success": True, "data": {...}} containing
        schema_version, tools_version, transports, tool_count, and the full
        tool manifest list.
    """
    try:
        logger.debug("Tool invoked: describe_mikrus_capabilities")
        result = _do_describe_mikrus_capabilities()
        logger.debug("Tool succeeded: describe_mikrus_capabilities")
        return _success_response(result, meta={"tool_version": TOOLS_VERSION})
    except Exception as e:
        logger.debug("Tool failed: describe_mikrus_capabilities — %s", e)
        return _error_response_extended(
            "INTERNAL_ERROR",
            str(e),
            True,
            suggestion="This is a zero-I/O tool — an error here indicates a code bug",
        )


def register_capability_tools(mcp: Any) -> None:
    """Register capability introspection tools on the given MCP instance."""
    mcp.tool(
        name="describe_mikrus_capabilities",
        description=_tool_description(
            "describe_mikrus_capabilities",
            "Returns the full tool catalog with capability manifests, supported transports, and schema version. Zero I/O, instant latency.",
        ),
    )(describe_mikrus_capabilities_tool)
