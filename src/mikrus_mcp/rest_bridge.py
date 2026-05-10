"""REST bridge — lightweight HTTP wrapper for MCP tools, exposed for smoke/e2e tests."""

from __future__ import annotations

import json
import logging
from typing import Any
from unittest.mock import MagicMock, patch

logger = logging.getLogger(__name__)


def create_rest_app(mcp: Any) -> Any:  # Starlette app, lazy import
    """Create a Starlette app that exposes all MCP tools as HTTP endpoints.

    Each tool is accessible via POST /tools/{name} with JSON body {"params": {}}.
    """
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def call_tool(request: Any) -> JSONResponse:
        tool_name = request.path_params["name"]
        try:
            body = await request.json()
        except Exception:
            body = {}
        params = body.get("params", {})

        lifespan = getattr(mcp, "_lifespan_data", None)

        if lifespan is None:
            return JSONResponse(
                {"success": False, "error": "Server lifespan not initialized"},
                status_code=503,
            )

        mock_ctx = MagicMock()
        mock_ctx.request_context.lifespan_context = lifespan

        try:
            with patch.object(mcp, "get_context", return_value=mock_ctx):
                result = await mcp.call_tool(tool_name, params)
        except Exception as exc:
            logger.error("Tool %s failed: %s", tool_name, exc)
            return JSONResponse(
                {"success": False, "error": str(exc)},
                status_code=500,
            )

        if isinstance(result, dict):
            return JSONResponse(result)
        if hasattr(result, "__iter__"):
            for block in result:
                if hasattr(block, "text"):
                    try:
                        return JSONResponse(json.loads(block.text))
                    except (json.JSONDecodeError, TypeError):
                        return JSONResponse({"success": True, "data": block.text})
        return JSONResponse({"success": True, "data": str(result)})

    async def list_tools_handler(request: Any) -> JSONResponse:  # noqa: ARG001
        tools_list = await mcp.list_tools()
        tools = [{"name": t.name} for t in tools_list]
        return JSONResponse({"success": True, "data": tools})

    async def health_handler(request: Any) -> JSONResponse:  # noqa: ARG001
        from mikrus_mcp.tools.constants import TOOL_MANIFESTS, TOOLS_VERSION

        return JSONResponse(
            {
                "status": "healthy",
                "tool_count": len(TOOL_MANIFESTS),
                "tools_version": TOOLS_VERSION,
            }
        )

    async def manifest_handler(request: Any) -> JSONResponse:  # noqa: ARG001
        from mikrus_mcp.tools.constants import TOOL_MANIFESTS

        tool_name = request.path_params["name"]
        manifest = TOOL_MANIFESTS.get(tool_name)
        if manifest is None:
            return JSONResponse(
                {"success": False, "error": f"No manifest for tool: {tool_name}"},
                status_code=404,
            )
        return JSONResponse({"success": True, "data": manifest})

    app = Starlette(
        routes=[
            Route("/api/health", health_handler, methods=["GET"]),
            Route("/api/tools", list_tools_handler, methods=["GET"]),
            Route("/api/tools/{name}", call_tool, methods=["POST"]),
            Route("/api/tools/{name}/manifest", manifest_handler, methods=["GET"]),
        ]
    )
    return app


async def run_rest_bridge(mcp: Any, port: int) -> None:
    """Start the REST bridge on the given port."""
    import uvicorn

    app = create_rest_app(mcp)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    await server.serve()
