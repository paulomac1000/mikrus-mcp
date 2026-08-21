from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("mcp", reason="official MCP SDK is required for the client contract")
from mcp import Client  # noqa: E402

from mikrus_mcp.approvals import ApprovalRegistry
from mikrus_mcp.config import Settings, TargetConfig
from mikrus_mcp.server import build_server
from mikrus_mcp.targets import TargetRegistry


class MockClient:
    def __init__(self, config: TargetConfig) -> None:
        self.stable_identity = config.stable_identity

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def get_server_info(self) -> dict[str, object]:
        return {
            "server_id": "abc123",
            "imie_id": "abc123",
            "server_name": None,
            "expires": "2027-02-13 00:00:00",
            "expires_storage": None,
            "param_ram": "1024",
            "param_disk": "15",
            "lastlog_panel": "2026-07-08 00:21:18",
            "mikrus_pro": "nie",
        }


@pytest.mark.asyncio
async def test_official_client_lists_schema_and_calls_tool() -> None:
    target = TargetConfig(
        "srv", "mikrus", api_url="https://api.mikr.us", api_key="k", server_id="srv"
    )
    settings = Settings(
        {"srv": target},
        "srv",
        allowed_scopes=frozenset(
            {"tool:*", "target:*", "target-id:*", "resource:*", "data:*", "write:server"}
        ),
    )
    registry = TargetRegistry(
        {"srv": target},
        factory=lambda value: MockClient(value),  # type: ignore[arg-type]
    )
    server = build_server(settings, registry=registry, approvals=ApprovalRegistry())
    async with Client(server, raise_exceptions=True) as client:
        listed = await client.list_tools()
        names = {tool.name for tool in listed.tools}
        assert "get_server_info" in names
        assert "write_file" not in names
        assert "execute_command" not in names
        result = await client.call_tool("get_server_info", {})
        assert result.is_error is not True
        assert result.structured_content is not None
        structured: dict[str, Any] = result.structured_content.get(
            "result", result.structured_content
        )
        assert structured["success"] is True
        assert structured["data"]["param_disk"] == "15"
