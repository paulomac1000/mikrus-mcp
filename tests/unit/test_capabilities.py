"""Unit tests for the capability introspection tool.

Reference: mcp-server-standards.md rule 2b (L3+ capability introspection).
[RULE: TEST-HIERARCHY-2] Zero I/O — no external dependencies.
"""

import json
from unittest.mock import patch

import pytest

from mikrus_mcp.tools.capabilities import (
    _do_describe_mikrus_capabilities,
    describe_mikrus_capabilities_tool,
    register_capability_tools,
)
from mikrus_mcp.tools.constants import CAPABILITIES_SCHEMA_VERSION, TOOLS_VERSION


class TestDoDescribeMikrusCapabilities:
    """Tests for the internal (zero-I/O) capabilities catalog builder."""

    def test_returns_schema_version(self) -> None:
        result = _do_describe_mikrus_capabilities()
        assert result["schema_version"] == CAPABILITIES_SCHEMA_VERSION

    def test_returns_tools_version(self) -> None:
        result = _do_describe_mikrus_capabilities()
        assert result["tools_version"] == TOOLS_VERSION

    def test_returns_transports(self) -> None:
        result = _do_describe_mikrus_capabilities()
        assert "stdio" in result["transports"]
        assert "sse" in result["transports"]

    def test_returns_tool_list(self) -> None:
        result = _do_describe_mikrus_capabilities()
        assert result["tool_count"] > 0
        assert len(result["tools"]) == result["tool_count"]
        assert isinstance(result["tools"], list)
        assert isinstance(result["tools"][0], dict)
        assert "name" in result["tools"][0]
        assert "risk" in result["tools"][0]

    def test_includes_all_registered_tools(self) -> None:
        from mikrus_mcp.tools.constants import TOOL_MANIFESTS

        result = _do_describe_mikrus_capabilities()
        assert result["tool_count"] == len(TOOL_MANIFESTS)


class TestDescribeMikrusCapabilitiesTool:
    """Tests for the tool wrapper (success and error paths)."""

    @pytest.mark.asyncio
    async def test_returns_success(self) -> None:
        result = await describe_mikrus_capabilities_tool()
        data = json.loads(result)
        assert data["success"] is True
        assert "tools" in data["data"]
        assert data["data"]["tool_count"] > 0

    @pytest.mark.asyncio
    async def test_exception_handler(self) -> None:
        with patch(
            "mikrus_mcp.tools.capabilities._do_describe_mikrus_capabilities",
            side_effect=RuntimeError("boom"),
        ):
            result = await describe_mikrus_capabilities_tool()

        data = json.loads(result)
        assert data["success"] is False
        assert "boom" in str(data["error"])


class TestRegisterCapabilityTools:
    """[RULE: TEST-REG-2] Registration test — mock MCP."""

    def test_registers_tool(self) -> None:
        from unittest.mock import MagicMock

        mock_mcp = MagicMock()
        mock_mcp._tools = {}

        def tool_decorator(*args: object, **kwargs: object) -> object:
            def wrapper(func: object) -> object:
                tool_name = kwargs.get("name", getattr(func, "__name__", "unknown"))
                assert isinstance(tool_name, str)
                mock_mcp._tools[tool_name] = func
                return func

            if len(args) == 1 and callable(args[0]) and not kwargs:
                name = getattr(args[0], "__name__", "unknown")
                assert isinstance(name, str)
                mock_mcp._tools[name] = args[0]
                return args[0]
            return wrapper

        mock_mcp.tool = tool_decorator

        register_capability_tools(mock_mcp)
        assert "describe_mikrus_capabilities" in mock_mcp._tools
