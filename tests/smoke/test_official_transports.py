from __future__ import annotations

import asyncio
import os
import socket
import sys
from typing import Any

import pytest

pytest.importorskip("mcp", reason="official MCP SDK is required for transport contracts")
httpx2 = pytest.importorskip("httpx2", reason="MCP v2 HTTP client dependency is required")
from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402
from mcp.client.streamable_http import streamable_http_client  # noqa: E402

from mikrus_mcp.approvals import ApprovalRegistry
from mikrus_mcp.config import Settings, TargetConfig
from mikrus_mcp.server import build_http_app, build_server
from mikrus_mcp.targets import TargetRegistry


class MockClient:
    def __init__(self, config: TargetConfig) -> None:
        self.stable_identity = config.stable_identity

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def get_server_info(self) -> dict[str, object]:
        return {"server_id": "srv", "source": "http-mock"}


@pytest.mark.asyncio
async def test_official_client_over_stdio_subprocess() -> None:
    environment = dict(os.environ)
    environment.update(
        {
            "PYTHONPATH": str((__import__("pathlib").Path(__file__).parents[2] / "src")),
            "MIKRUS_API_KEY": "test-key",
            "MIKRUS_SERVER_NAME": "srv",
            "MCP_TRANSPORT": "stdio",
        }
    )
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mikrus_mcp"],
        env=environment,
    )
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            names = {tool.name for tool in listed.tools}
            assert "describe_mikrus_capabilities" in names
            assert "execute_command" not in names
            result = await session.call_tool("describe_mikrus_capabilities", arguments={})
            assert result.is_error is not True
            assert result.structured_content is not None


@pytest.mark.asyncio
async def test_official_client_over_authenticated_streamable_http() -> None:
    import uvicorn

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    listener.setblocking(False)
    port = int(listener.getsockname()[1])
    token = "t" * 48
    target = TargetConfig(
        "srv", "mikrus", api_url="https://api.mikr.us", api_key="k", server_id="srv"
    )
    settings = Settings(
        {"srv": target},
        "srv",
        transport="streamable-http",
        host="127.0.0.1",
        port=port,
        http_bearer_token=token,
        allowed_scopes=frozenset({"tool:*", "target:*", "write:server"}),
    )
    registry = TargetRegistry(
        {"srv": target}, factory=lambda value: MockClient(value)  # type: ignore[arg-type]
    )
    app = build_http_app(
        build_server(settings, registry=registry, approvals=ApprovalRegistry()), settings
    )
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
    )
    task = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        for _ in range(200):
            if server.started:
                break
            await asyncio.sleep(0.01)
        assert server.started
        async with httpx2.AsyncClient(
            headers={"Authorization": f"Bearer {token}"}
        ) as http_client:
            async with streamable_http_client(
                f"http://127.0.0.1:{port}/mcp", http_client=http_client
            ) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool("get_server_info", arguments={})
                    assert result.is_error is not True
                    assert result.structured_content is not None
                    structured: dict[str, Any] = result.structured_content.get(
                        "result", result.structured_content
                    )
                    assert structured["data"]["source"] == "http-mock"
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=10)
        listener.close()
