"""MCPWrapper — abstracts FastMCP internals for integration tests.

Follows Canonical Template 8 from mcp_standards.md.
"""

import asyncio
import json
from typing import Any
from unittest.mock import MagicMock, patch


class MCPWrapper:
    """Wraps a FastMCP instance to provide a stable call_tool interface.

    Probes multiple internal storage locations to discover registered tools,
    handles async execution, and patches get_context for lifespan data.
    """

    def __init__(self, mcp: Any, lifespan_data: dict[str, Any]) -> None:
        self._mcp = mcp
        self._lifespan_data = lifespan_data
        self._tools: dict[str, Any] = {}
        self._discover_tools()

    def _discover_tools(self) -> None:
        """Probe multiple FastMCP internal storage locations."""
        mcp = self._mcp
        if hasattr(mcp, "_tools") and isinstance(mcp._tools, dict):
            self._tools.update(mcp._tools)
        if hasattr(mcp, "_tool_manager"):
            tm = mcp._tool_manager
            if hasattr(tm, "_tools") and isinstance(tm._tools, dict):
                for name, tool in tm._tools.items():
                    self._tools[name] = self._unwrap_tool(tool)
        if hasattr(mcp, "tools"):
            try:
                tools_dict = mcp.tools
                if isinstance(tools_dict, dict):
                    for name, tool in tools_dict.items():
                        self._tools[name] = self._unwrap_tool(tool)
            except Exception:
                pass

    def _unwrap_tool(self, tool: Any) -> Any:
        """Extract the callable from a Tool object by checking common attributes."""
        for attr in ("fn", "func", "_func", "function"):
            if hasattr(tool, attr):
                return getattr(tool, attr)
        return tool

    def list_tools(self) -> list[str]:
        """Return list of registered tool names."""
        return sorted(self._tools.keys())

    async def call_tool(self, tool_name: str, **kwargs: Any) -> dict[str, Any]:
        """Call a tool by name with kwargs and return parsed JSON response."""
        # Set lifespan data on the MCP instance for the REST bridge pattern
        self._mcp._lifespan_data = self._lifespan_data

        mock_ctx = MagicMock()
        mock_ctx.request_context.lifespan_context = self._lifespan_data

        with patch.object(self._mcp, "get_context", return_value=mock_ctx):
            result = await self._mcp.call_tool(tool_name, kwargs)

        # FastMCP 1.27+ with output_schema returns tuple (list[ContentBlock], dict)
        if isinstance(result, tuple):
            result = result[0]  # Unstructured content: list[ContentBlock]

        # FastMCP.call_tool returns a list of Content objects (or similar)
        # Extract text from the result
        if isinstance(result, dict):
            return result
        if hasattr(result, "__iter__"):
            for block in result:
                if hasattr(block, "text"):
                    try:
                        parsed = json.loads(block.text)
                        assert isinstance(parsed, dict)
                        return parsed
                    except (json.JSONDecodeError, TypeError, AssertionError):
                        return {"success": True, "data": str(block.text)}
        return {"success": True, "data": str(result)}

    def call_tool_sync(self, tool_name: str, **kwargs: Any) -> dict[str, Any]:
        """Synchronous wrapper for call_tool.

        Creates a new event loop if one is not available.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(self.call_tool(tool_name, **kwargs))

        # Running in an existing event loop
        return loop.run_until_complete(self.call_tool(tool_name, **kwargs))
