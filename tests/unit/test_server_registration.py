from __future__ import annotations

import inspect

import pytest

pytest.importorskip("mcp", reason="official MCP SDK is required for registration contracts")
from mcp import Client  # noqa: E402

from mikrus_mcp.config import Settings, TargetConfig
from mikrus_mcp.manifests import active_names
from mikrus_mcp.server import build_http_app, build_server


def settings(*, transport: str = "stdio") -> Settings:
    target = TargetConfig(
        "srv", "mikrus", api_url="https://api.mikr.us", api_key="k", server_id="srv"
    )
    return Settings(
        {"srv": target},
        "srv",
        transport=transport,  # type: ignore[arg-type]
        host="127.0.0.1",
        http_bearer_token="x" * 32 if transport == "streamable-http" else None,
    )


@pytest.mark.asyncio
async def test_registration_matches_active_manifests() -> None:
    current = settings()
    async with Client(build_server(current), raise_exceptions=True) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
    assert names == active_names(current)
    assert "execute_command" not in names


def test_mutating_tool_schemas_do_not_expose_approval_tokens() -> None:
    from mikrus_mcp import server as module

    for name in (
        "restart_server",
        "boost_server",
        "assign_domain",
        "write_file",
        "change_service_state",
        "terminate_process",
        "update_system",
    ):
        signature = inspect.signature(getattr(module, name))
        assert "approval_token" not in signature.parameters


def test_http_builder_requires_streamable_http_settings() -> None:
    current = settings()
    with pytest.raises(ValueError, match="streamable-http"):
        build_http_app(build_server(current), current)


def test_http_builder_accepts_authenticated_streamable_http_settings() -> None:
    current = settings(transport="streamable-http")
    app = build_http_app(build_server(current), current)
    assert callable(app)
