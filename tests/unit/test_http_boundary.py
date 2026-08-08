from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pytest

from mikrus_mcp.http import (
    AUTH_SCOPE_KEY,
    BearerAuthMiddleware,
    LoopbackOriginMiddleware,
    RequestBodyLimitMiddleware,
    bearer_principal,
)


async def run_asgi(
    app: Any,
    scope: dict[str, Any],
    messages: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    iterator = iter(messages)
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return next(iterator)

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await app(scope, receive, send)
    return sent


@pytest.mark.asyncio
async def test_oversized_chunked_body_is_rejected_before_application() -> None:
    called = False

    async def inner(scope: dict[str, Any], receive: Any, send: Any) -> None:
        nonlocal called
        called = True

    middleware = RequestBodyLimitMiddleware(inner, 1024)
    sent = await run_asgi(
        middleware,
        {"type": "http", "headers": []},
        [
            {"type": "http.request", "body": b"a" * 700, "more_body": True},
            {"type": "http.request", "body": b"b" * 700, "more_body": False},
        ],
    )
    assert called is False
    assert sent[0]["status"] == 413


@pytest.mark.asyncio
async def test_conflicting_content_length_is_rejected() -> None:
    async def inner(scope: dict[str, Any], receive: Any, send: Any) -> None:
        raise AssertionError("application should not be called")

    middleware = RequestBodyLimitMiddleware(inner, 1024)
    sent = await run_asgi(
        middleware,
        {
            "type": "http",
            "headers": [(b"content-length", b"1"), (b"content-length", b"2")],
        },
        [{"type": "http.request", "body": b"a", "more_body": False}],
    )
    assert sent[0]["status"] == 400


@pytest.mark.asyncio
async def test_host_and_origin_are_loopback_bound() -> None:
    async def inner(scope: dict[str, Any], receive: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = LoopbackOriginMiddleware(inner, "127.0.0.1", 8000)
    allowed = await run_asgi(
        middleware,
        {
            "type": "http",
            "headers": [
                (b"host", b"127.0.0.1:8000"),
                (b"origin", b"http://127.0.0.1:8000"),
            ],
        },
        [],
    )
    assert allowed[0]["status"] == 204

    denied = await run_asgi(
        middleware,
        {
            "type": "http",
            "headers": [
                (b"host", b"evil.example"),
                (b"origin", b"https://evil.example"),
            ],
        },
        [],
    )
    assert denied[0]["status"] == 403


@pytest.mark.asyncio
async def test_empty_origin_is_accepted_for_non_browser_clients() -> None:
    async def inner(scope: dict[str, Any], receive: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = LoopbackOriginMiddleware(inner, "127.0.0.1", 8000)
    sent = await run_asgi(
        middleware,
        {"type": "http", "headers": [(b"host", b"127.0.0.1:8000")]},
        [],
    )
    assert sent[0]["status"] == 200


@pytest.mark.asyncio
async def test_bearer_auth_rejects_before_application_and_binds_request_identity() -> None:
    called = False
    observed: dict[str, Any] = {}
    token = "x" * 32

    async def inner(scope: dict[str, Any], receive: Any, send: Any) -> None:
        nonlocal called
        called = True
        observed.update(scope)
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = BearerAuthMiddleware(inner, token, frozenset({"tool:*", "target:prod"}))
    denied = await run_asgi(
        middleware,
        {"type": "http", "headers": [(b"authorization", b"Bearer wrong")]},
        [],
    )
    assert denied[0]["status"] == 401
    assert called is False

    allowed = await run_asgi(
        middleware,
        {"type": "http", "headers": [(b"authorization", b"Bearer " + b"x" * 32)]},
        [],
    )
    assert allowed[0]["status"] == 204
    assert observed[AUTH_SCOPE_KEY] == {
        "principal": bearer_principal(token),
        "scopes": ("target:prod", "tool:*"),
    }
