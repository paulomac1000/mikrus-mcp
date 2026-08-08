"""Official MCP Python SDK v2 composition root and transport entry point."""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from mcp.server.mcpserver import MCPServer

from mikrus_mcp.approvals import ApprovalRegistry
from mikrus_mcp.config import Settings, load_settings
from mikrus_mcp.http import (
    BearerAuthMiddleware,
    LoopbackOriginMiddleware,
    RequestBodyLimitMiddleware,
)
from mikrus_mcp.kernel import InvocationKernel
from mikrus_mcp.manifests import active_names, validate_manifests
from mikrus_mcp.targets import TargetRegistry
from mikrus_mcp.tool_api import TOOL_FUNCTIONS
from mikrus_mcp.tool_common import AppContext

logger = logging.getLogger(__name__)


def build_server(
    settings: Settings | None = None,
    *,
    registry: TargetRegistry | None = None,
    approvals: ApprovalRegistry | None = None,
) -> MCPServer[AppContext]:
    settings = (settings or load_settings()).validate()
    kernel = InvocationKernel(settings, registry=registry, approvals=approvals)

    @asynccontextmanager
    async def lifespan(_: MCPServer[AppContext]) -> AsyncIterator[AppContext]:
        try:
            yield AppContext(settings, kernel)
        finally:
            await kernel.close()

    server = MCPServer(
        "mikrus-mcp",
        version="2.0.0",
        instructions=(
            "Call list_configured_servers before selecting a target. Preserve the exact target "
            "identifier. Never retry a mutation. Mutations require operator enablement and a "
            "one-time server-side approval bound to capability, principal, target, and resource."
        ),
        lifespan=lifespan,
    )
    registered = active_names(settings)
    for name in sorted(registered):
        server.tool(structured_output=True)(TOOL_FUNCTIONS[name])
    validate_manifests(set(registered), settings)

    @server.resource("capabilities://catalog", mime_type="application/json")
    async def capability_catalog() -> str:
        return json.dumps(kernel.catalog(active_only=False), sort_keys=True)

    @server.resource("health://ready", mime_type="application/json")
    async def readiness() -> str:
        return json.dumps(
            {
                "ready": True,
                "transport": settings.transport,
                "configured_targets": len(settings.targets),
                "active_capabilities": len(kernel.active_names),
                "write_enabled": settings.write_enabled,
            },
            sort_keys=True,
        )

    @server.prompt()
    def safe_administration_workflow() -> str:
        return (
            "Discover targets, select one exact identifier, read current state, plan changes, "
            "obtain trusted approval outside the model, execute once, then verify postconditions."
        )

    return server


def build_http_app(server: MCPServer[AppContext], settings: Settings) -> Any:
    if settings.transport != "streamable-http":
        raise ValueError("build_http_app requires streamable-http settings")
    app = server.streamable_http_app(
        host=settings.host,
        json_response=True,
        stateless_http=True,
        max_request_body_size=settings.max_request_body_bytes,
    )
    if settings.http_bearer_token is None:
        raise ValueError("Streamable HTTP bearer token is not configured")
    return BearerAuthMiddleware(
        LoopbackOriginMiddleware(
            RequestBodyLimitMiddleware(app, settings.max_request_body_bytes),
            settings.host,
            settings.port,
        ),
        settings.http_bearer_token,
        settings.allowed_scopes,
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    settings = load_settings()
    server = build_server(settings)
    if settings.transport == "stdio":
        server.run()
    else:
        uvicorn.run(build_http_app(server, settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
