"""Typed public MCP tool callables delegating to the invocation kernel."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, TypedDict, cast

from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import JsonValue

from mikrus_mcp.config import Settings
from mikrus_mcp.http import AUTH_SCOPE_KEY
from mikrus_mcp.kernel import CallerContext, InvocationKernel


class ToolResult(TypedDict):
    """Protocol-visible successful tool result with provenance metadata."""

    success: Literal[True]
    data: JsonValue
    _meta: JsonValue


@dataclass(frozen=True, slots=True)
class AppContext:
    settings: Settings
    kernel: InvocationKernel


def _caller(ctx: Context[AppContext]) -> CallerContext:
    settings = ctx.request_context.lifespan_context.settings
    if settings.transport != "streamable-http":
        return CallerContext(
            principal=settings.principal,
            scopes=settings.allowed_scopes,
        )

    request = ctx.request_context.request
    scope = getattr(request, "scope", None)
    authenticated = scope.get(AUTH_SCOPE_KEY) if isinstance(scope, Mapping) else None
    if not isinstance(authenticated, Mapping):
        raise ToolError("AUTHENTICATION: authenticated HTTP principal is missing")
    principal = authenticated.get("principal")
    scopes = authenticated.get("scopes")
    if not isinstance(principal, str) or not principal:
        raise ToolError("AUTHENTICATION: authenticated HTTP principal is invalid")
    if not isinstance(scopes, (tuple, list)) or any(
        not isinstance(scope_name, str) or not scope_name for scope_name in scopes
    ):
        raise ToolError("AUTHENTICATION: authenticated HTTP scopes are invalid")
    return CallerContext(principal=principal, scopes=frozenset(scopes))


def _require_success(result: dict[str, Any]) -> ToolResult:
    if result.get("success") is True:
        return {
            "success": True,
            "data": cast(JsonValue, result.get("data")),
            "_meta": cast(JsonValue, result.get("_meta") or {}),
        }
    error = result.get("error") or {}
    payload = {
        "success": False,
        "error": error,
        "_meta": result.get("_meta") or {},
    }
    raise ToolError(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


async def _invoke(
    ctx: Context[AppContext],
    name: str,
    arguments: dict[str, Any],
) -> ToolResult:
    kernel = ctx.request_context.lifespan_context.kernel
    return _require_success(await kernel.invoke(name, arguments, _caller(ctx)))
