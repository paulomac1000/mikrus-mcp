"""Real-system e2e tests for a running mikrus-mcp server and the real mikr.us API.

All tests skip cleanly when the required environment is absent.

Instance connectivity tests (no marker):
  MCP_TEST_HTTP_URL   — Streamable HTTP endpoint (default http://127.0.0.1:8300/mcp)
  MCP_TEST_HTTP_TOKEN — Bearer token value, or path to a text file containing the token

Real mikr.us API tests (marker real_backend):
  MIKRUS_API_KEY     — mikr.us API key
  MIKRUS_SERVER_NAME — mikr.us server identifier

Running the live tests:
  MCP_TEST_HTTP_TOKEN=$(cat .mcp-http-token) \\
    MIKRUS_API_KEY=... MIKRUS_SERVER_NAME=srv... \\
    .venv/bin/python -m pytest tests/real_system -v

To run only real_backend tests:
  MIKRUS_API_KEY=... MIKRUS_SERVER_NAME=srv... \\
    .venv/bin/python -m pytest tests/real_system -v -m real_backend
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp", reason="official MCP SDK is required for transport contracts")
httpx2 = pytest.importorskip("httpx2", reason="MCP v2 HTTP client dependency is required")
import httpx  # noqa: E402 — used for pre-flight connectivity probe
from mcp import ClientSession  # noqa: E402
from mcp.client.streamable_http import streamable_http_client  # noqa: E402

_SENSITIVE_RESPONSE_KEYS = frozenset({"password", "passwd", "pwd", "secret", "token", "api_key"})

# --------------------------------------------------------------------------- helpers


def _http_url() -> str:
    return os.environ.get("MCP_TEST_HTTP_URL", "http://127.0.0.1:8300/mcp")


def _http_token() -> str | None:
    raw = os.environ.get("MCP_TEST_HTTP_TOKEN")
    if raw is None:
        return None
    if raw.startswith("/") or raw.startswith("./") or raw.startswith("../"):
        try:
            return Path(raw).read_text(encoding="utf-8").strip()
        except OSError:
            return None
    return raw


def _instance_reachable() -> bool:
    """Quick connectivity probe — returns True when the MCP endpoint responds."""
    url = _http_url()
    try:
        # Some deployments expose a health endpoint alongside /mcp.
        probe = url.replace("/mcp", "/health")
        resp = httpx.get(probe, timeout=2.0)
        return resp.status_code < 500
    except Exception:
        try:
            httpx.post(url, timeout=2.0)
            return True
        except Exception:
            return False


# ------------------------------------------------------------------ HTTP instance


@pytest.mark.asyncio
async def test_official_client_over_streamable_http_lists_tools() -> None:
    token = _http_token()
    if token is None:
        pytest.skip("MCP_TEST_HTTP_TOKEN environment variable is not set")
    url = _http_url()
    if not _instance_reachable():
        pytest.skip(f"MCP instance at {url} is unreachable")

    async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}) as http_client:
        async with streamable_http_client(url, http_client=http_client) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                names = {tool.name for tool in listed.tools}
                assert "get_server_info" in names, "expected get_server_info in tool list"
                assert "execute_command" not in names, "execute_command must not be exposed"


@pytest.mark.asyncio
async def test_get_server_info_over_http_returns_sanitized_data() -> None:
    token = _http_token()
    if token is None:
        pytest.skip("MCP_TEST_HTTP_TOKEN environment variable is not set")
    url = _http_url()
    if not _instance_reachable():
        pytest.skip(f"MCP instance at {url} is unreachable")

    async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}) as http_client:
        async with streamable_http_client(url, http_client=http_client) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("get_server_info", arguments={})
                assert result.is_error is not True, (
                    f"get_server_info returned error: {result.content}"
                )
                assert result.structured_content is not None

                structured: dict[str, Any] = result.structured_content.get(
                    "result", result.structured_content
                )

                data = structured.get("data", {})
                assert isinstance(data, dict), f"expected dict, got {type(data).__name__}"

                # Assert no credential fields leaked in top-level data keys.
                data_keys_lower = {str(k).lower() for k in data}
                leaked = data_keys_lower & _SENSITIVE_RESPONSE_KEYS
                assert not leaked, f"credential field(s) leaked: {sorted(leaked)}"


@pytest.mark.asyncio
async def test_write_file_without_approval_fails_closed() -> None:
    token = _http_token()
    if token is None:
        pytest.skip("MCP_TEST_HTTP_TOKEN environment variable is not set")
    url = _http_url()
    if not _instance_reachable():
        pytest.skip(f"MCP instance at {url} is unreachable")

    async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}) as http_client:
        async with streamable_http_client(url, http_client=http_client) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "write_file",
                    arguments={"path": "/tmp/mcp-real-system-test", "content": "e2e-probe"},
                )
                assert result.is_error is True, (
                    "write_file without approval must fail closed — expected is_error=True"
                )


# ------------------------------------------------------------- real mikr.us API

_MIKRUS_API_KEY = os.environ.get("MIKRUS_API_KEY")
_MIKRUS_SERVER_NAME = os.environ.get("MIKRUS_SERVER_NAME")

# Capture names only — never print or log values.
_HAS_MIKRUS_CREDS = bool(_MIKRUS_API_KEY and _MIKRUS_SERVER_NAME)


async def _real_client() -> Any:
    """Create and open a MikrusClient against the real API."""
    from mikrus_mcp.clients.mikrus import MikrusClient  # noqa: E402

    # High rpm keeps the live burst test inside the credential limiter's design
    # envelope (default 5/min fail-fasts a second call within 12 seconds).
    client = MikrusClient(
        "https://api.mikr.us", _MIKRUS_API_KEY, _MIKRUS_SERVER_NAME, requests_per_minute=10_000
    )
    await client.open()
    return client


@pytest.mark.real_backend
@pytest.mark.asyncio
async def test_mikrus_get_server_info_returns_shape() -> None:
    if not _HAS_MIKRUS_CREDS:
        pytest.skip("TODO(real-system): MIKRUS_API_KEY and MIKRUS_SERVER_NAME env vars required")

    client = await _real_client()
    try:
        result = await client.get_server_info()
        assert isinstance(result, dict), f"expected dict, got {type(result).__name__}"
        for key in ("server_id", "imie_id", "param_ram"):
            assert key in result, f"missing key '{key}' in get_server_info response"
    finally:
        await client.close()


@pytest.mark.real_backend
@pytest.mark.asyncio
async def test_mikrus_get_ports_returns_list() -> None:
    if not _HAS_MIKRUS_CREDS:
        pytest.skip("TODO(real-system): MIKRUS_API_KEY and MIKRUS_SERVER_NAME env vars required")

    client = await _real_client()
    try:
        result = await client.get_ports()
        # The mikr.us /porty endpoint may return a list directly or a dict containing one.
        if isinstance(result, dict):
            ports = result.get("porty", result.get("ports", result))
            assert isinstance(ports, list), f"expected list in response, got {type(ports).__name__}"
        else:
            assert isinstance(result, list), f"expected list, got {type(result).__name__}"
    finally:
        await client.close()


@pytest.mark.real_backend
@pytest.mark.asyncio
async def test_mikrus_list_servers_contains_configured() -> None:
    if not _HAS_MIKRUS_CREDS:
        pytest.skip("TODO(real-system): MIKRUS_API_KEY and MIKRUS_SERVER_NAME env vars required")

    client = await _real_client()
    try:
        result = await client.list_servers()
        # The /serwery endpoint may return a list or a dict.
        servers: list[dict[str, Any]] = []
        if isinstance(result, list):
            servers = result
        elif isinstance(result, dict):
            servers = result.get("serwery", result.get("data", []))
            if not isinstance(servers, list):
                servers = []

        server_ids = {
            str(s.get("server_id") or s.get("id") or s.get("name") or "")
            for s in servers
            if isinstance(s, dict)
        }
        assert _MIKRUS_SERVER_NAME in server_ids, (
            f"configured server '{_MIKRUS_SERVER_NAME}' not found in list_servers response"
        )
    finally:
        await client.close()


@pytest.mark.real_backend
@pytest.mark.asyncio
async def test_mikrus_rate_limiter_sequential_calls_succeed() -> None:
    if not _HAS_MIKRUS_CREDS:
        pytest.skip("TODO(real-system): MIKRUS_API_KEY and MIKRUS_SERVER_NAME env vars required")

    client = await _real_client()
    try:
        # Two quick sequential calls — must not trigger RATE_LIMITED.
        result1 = await client.get_server_info()
        assert isinstance(result1, dict), "first get_server_info call failed"
        result2 = await client.get_logs()
        # get_logs returns a list of log entries; shape varies but must be iterable.
        assert isinstance(result2, (list, dict)), (
            f"expected list or dict from get_logs, got {type(result2).__name__}"
        )
    finally:
        await client.close()
