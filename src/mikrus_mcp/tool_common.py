"""Typed public MCP tool callables delegating to the invocation kernel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, TypedDict, cast

from pydantic import JsonValue

from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError

from mikrus_mcp.config import Settings
from mikrus_mcp.kernel import CallerContext, InvocationKernel


class ToolResult(TypedDict):
    """Protocol-visible successful tool result with a concrete output schema."""

    success: Literal[True]
    data: JsonValue


@dataclass(frozen=True, slots=True)
class AppContext:
    settings: Settings
    kernel: InvocationKernel


def _caller(ctx: Context[AppContext]) -> CallerContext:
    settings = ctx.request_context.lifespan_context.settings
    return CallerContext(settings.principal, settings.allowed_scopes)


def _require_success(result: dict[str, Any]) -> ToolResult:
    if result.get("success") is True:
        return {
            "success": True,
            "data": cast(JsonValue, result.get("data")),
        }
    error = result.get("error") or {}
    code = str(error.get("code", "ERROR"))
    message = str(error.get("message", "operation failed"))
    raise ToolError(f"{code}: {message}")


async def _invoke(
    ctx: Context[AppContext],
    name: str,
    arguments: dict[str, Any],
) -> ToolResult:
    kernel = ctx.request_context.lifespan_context.kernel
    return _require_success(await kernel.invoke(name, arguments, _caller(ctx)))
