"""Loopback-only ASGI controls around Streamable HTTP."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
from typing import Any, Final, cast
from urllib.parse import urlsplit

AUTH_SCOPE_KEY: Final = "mikrus_mcp.authenticated_caller"


def bearer_principal(token: str) -> str:
    """Derive a stable non-secret principal identifier from one bearer credential."""
    if not isinstance(token, str) or len(token) < 32:
        raise ValueError("HTTP bearer token must contain at least 32 characters")
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"bearer-sha256:{digest}"


class RequestBodyLimitMiddleware:
    """Reject oversized or fragmented bodies before MCP parsing."""

    def __init__(self, app: Any, max_bytes: int, max_events: int = 1_024) -> None:
        if not 1_024 <= max_bytes <= 16_777_216:
            raise ValueError("max_bytes must be between 1024 and 16777216")
        if not 1 <= max_events <= 10_000:
            raise ValueError("max_events must be between 1 and 10000")
        self._app = app
        self._max_bytes = max_bytes
        self._max_events = max_events

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return
        declared: list[int] = []
        for key, value in scope.get("headers", []):
            if key.lower() != b"content-length":
                continue
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                await self._reject(send, 400, b"invalid content-length")
                return
            if parsed < 0:
                await self._reject(send, 400, b"invalid content-length")
                return
            declared.append(parsed)
        if declared and any(value != declared[0] for value in declared):
            await self._reject(send, 400, b"conflicting content-length")
            return
        if declared and declared[0] > self._max_bytes:
            await self._reject(send, 413, b"request body too large")
            return

        body = bytearray()
        for event_number in range(1, self._max_events + 2):
            if event_number > self._max_events:
                await self._reject(send, 413, b"too many request body chunks")
                return
            message = await receive()
            if message.get("type") == "http.disconnect":
                return
            if message.get("type") != "http.request":
                await self._reject(send, 400, b"invalid request body event")
                return
            chunk = message.get("body", b"")
            if not isinstance(chunk, bytes):
                await self._reject(send, 400, b"invalid request body")
                return
            body.extend(chunk)
            if len(body) > self._max_bytes:
                await self._reject(send, 413, b"request body too large")
                return
            if message.get("more_body") is not True:
                break
        if declared and len(body) != declared[0]:
            await self._reject(send, 400, b"content-length mismatch")
            return

        replayed = False

        async def replay_receive() -> dict[str, Any]:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return cast(dict[str, Any], await receive())

        await self._app(scope, replay_receive, send)

    @staticmethod
    async def _reject(send: Any, status: int, body: bytes) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"text/plain; charset=utf-8")],
            }
        )
        await send({"type": "http.response.body", "body": body})


class LoopbackOriginMiddleware:
    """Validate Host and Origin against the configured literal loopback endpoint."""

    def __init__(self, app: Any, host: str, port: int) -> None:
        address = ipaddress.ip_address(host)
        if not address.is_loopback:
            raise ValueError("HTTP host must be loopback")
        self._app = app
        self._host = host
        self._port = port
        bracketed = f"[{host}]" if address.version == 6 else host
        self._allowed_authorities = {bracketed, f"{bracketed}:{port}"}

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return
        headers: dict[bytes, list[bytes]] = {}
        for key, value in scope.get("headers", []):
            headers.setdefault(key.lower(), []).append(value)
        host_values = headers.get(b"host", [])
        if len(host_values) != 1:
            await RequestBodyLimitMiddleware._reject(send, 400, b"exactly one Host is required")
            return
        try:
            authority = host_values[0].decode("ascii").casefold()
        except UnicodeDecodeError:
            await RequestBodyLimitMiddleware._reject(send, 400, b"invalid Host")
            return
        if authority not in {item.casefold() for item in self._allowed_authorities}:
            await RequestBodyLimitMiddleware._reject(send, 403, b"Host is not allowed")
            return

        origins = headers.get(b"origin", [])
        if len(origins) > 1:
            await RequestBodyLimitMiddleware._reject(send, 400, b"multiple Origin headers")
            return
        if origins:
            try:
                parsed = urlsplit(origins[0].decode("ascii"))
            except (UnicodeDecodeError, ValueError):
                await RequestBodyLimitMiddleware._reject(send, 400, b"invalid Origin")
                return
            if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
                await RequestBodyLimitMiddleware._reject(send, 403, b"Origin is not allowed")
                return
            origin_host = parsed.hostname
            origin_port = parsed.port or (443 if parsed.scheme == "https" else 80)
            try:
                address = ipaddress.ip_address(origin_host or "")
            except ValueError:
                await RequestBodyLimitMiddleware._reject(send, 403, b"Origin is not allowed")
                return
            if not address.is_loopback or origin_port != self._port:
                await RequestBodyLimitMiddleware._reject(send, 403, b"Origin is not allowed")
                return
        await self._app(scope, receive, send)


class BearerAuthMiddleware:
    """Authenticate HTTP and attach a request-scoped caller identity to ASGI scope."""

    def __init__(self, app: Any, token: str, scopes: frozenset[str]) -> None:
        self._app = app
        self._expected = f"Bearer {token}".encode()
        self._principal = bearer_principal(token)
        if not scopes or any(not isinstance(scope, str) or not scope for scope in scopes):
            raise ValueError("HTTP authorization scopes must be non-empty strings")
        self._scopes = tuple(sorted(scopes))

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return
        values = [
            value for key, value in scope.get("headers", []) if key.lower() == b"authorization"
        ]
        if len(values) != 1 or not hmac.compare_digest(values[0], self._expected):
            await RequestBodyLimitMiddleware._reject(send, 401, b"authentication required")
            return
        authenticated_scope = dict(scope)
        authenticated_scope[AUTH_SCOPE_KEY] = {
            "principal": self._principal,
            "scopes": self._scopes,
        }
        await self._app(authenticated_scope, receive, send)
