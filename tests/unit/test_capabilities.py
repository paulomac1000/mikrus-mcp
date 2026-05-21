"""Unit tests for the capability introspection tool.

Reference: mcp-server-standards.md rule 2b (L3+ capability introspection).
[RULE: TEST-HIERARCHY-2] Zero I/O — no external dependencies.
"""

import json
from unittest.mock import MagicMock, patch

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
    async def test_returns_success_and_meta_envelope(self) -> None:
        result = await describe_mikrus_capabilities_tool()
        data = json.loads(result)
        assert data["success"] is True
        assert "tools" in data["data"]
        assert data["data"]["tool_count"] > 0
        assert "_meta" in data
        assert "request_id" in data["_meta"]
        assert data["_meta"]["tool_version"] == TOOLS_VERSION

    @pytest.mark.asyncio
    async def test_exception_handler(self) -> None:
        with patch(
            "mikrus_mcp.tools.capabilities._do_describe_mikrus_capabilities",
            side_effect=RuntimeError("boom"),
        ):
            result = await describe_mikrus_capabilities_tool()

        data = json.loads(result)
        assert data["success"] is False
        assert isinstance(data["error"], dict)
        assert data["error"]["code"] == "INTERNAL_ERROR"
        assert data["error"]["message"] == "boom"
        assert data["error"]["retryable"] is True
        assert "_meta" in data
        assert "request_id" in data["_meta"]


class TestRegisterCapabilityTools:
    """[RULE: TEST-REG-2] Registration test — uses mock_mcp fixture."""

    def test_registers_tool(self, mock_mcp: MagicMock) -> None:
        register_capability_tools(mock_mcp)
        assert "describe_mikrus_capabilities" in mock_mcp._tools
