from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from mikrus_mcp.client import MikrusClient
from mikrus_mcp.errors import AppError, ErrorCode

INFO_RESPONSE: dict[str, object] = {
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

DB_RESPONSE = {
    "db_user": "abc123",
    "db_host": "db.mikr.us",
    "db_port": "3306",
    "db_name": "abc123",
    "password": "redacted-secret",
}


@pytest.mark.asyncio
async def test_http_request_binds_credentials_and_target() -> None:
    observed: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return httpx.Response(200, json=INFO_RESPONSE, request=request)

    client = MikrusClient(
        "https://api.mikr.us",
        "key",
        "srv",
        requests_per_minute=100_000,
        transport=httpx.MockTransport(handler),
    )
    async with client:
        result = await client.get_server_info()
    assert result["param_ram"] == "1024"
    assert observed[0].headers["authorization"] == "Bearer key"
    assert b"srv=srv" in observed[0].content and b"key=key" in observed[0].content


@pytest.mark.asyncio
async def test_local_rate_limit_returns_retry_guidance_without_waiting() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=DB_RESPONSE, request=request)

    client = MikrusClient(
        "https://api.mikr.us",
        "key",
        "srv",
        requests_per_minute=5,
        transport=httpx.MockTransport(handler),
    )
    async with client:
        await client.get_db_info()
        with pytest.raises(AppError) as caught:
            await client.get_db_info()
    assert caught.value.code is ErrorCode.RATE_LIMITED
    assert caught.value.retry_after_seconds is not None
    assert 0 < caught.value.retry_after_seconds <= 12
    assert calls == 1


@pytest.mark.asyncio
async def test_adapter_performs_one_attempt_for_reads_and_mutations() -> None:
    read_calls = 0

    async def read_handler(request: httpx.Request) -> httpx.Response:
        nonlocal read_calls
        read_calls += 1
        return httpx.Response(429, headers={"Retry-After": "0"}, request=request)

    read = MikrusClient(
        "https://api.mikr.us",
        "key",
        "srv",
        requests_per_minute=100_000,
        transport=httpx.MockTransport(read_handler),
    )
    async with read:
        with pytest.raises(AppError) as caught:
            await read.get_server_info()
    assert caught.value.code is ErrorCode.RATE_LIMITED
    assert caught.value.retryable is False
    assert read_calls == 1

    mutation_calls = 0

    async def mutation_handler(request: httpx.Request) -> httpx.Response:
        nonlocal mutation_calls
        mutation_calls += 1
        return httpx.Response(429, headers={"Retry-After": "0"}, request=request)

    mutation = MikrusClient(
        "https://api.mikr.us",
        "key",
        "srv",
        requests_per_minute=100_000,
        transport=httpx.MockTransport(mutation_handler),
    )
    async with mutation:
        with pytest.raises(AppError) as caught:
            await mutation.restart_server()
    assert caught.value.code is ErrorCode.RATE_LIMITED
    assert caught.value.retryable is False
    assert mutation_calls == 1


@pytest.mark.asyncio
async def test_credentials_endpoint_is_not_cached() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={**DB_RESPONSE, "password": f"redacted-secret-{calls}"},
            request=request,
        )

    client = MikrusClient(
        "https://api.mikr.us",
        "key",
        "srv",
        requests_per_minute=100_000,
        transport=httpx.MockTransport(handler),
    )
    async with client:
        await client.get_db_info()
        # The sleep must exceed one rate-limiter slot (60s / 100_000 rpm), or the
        # credential limiter legitimately throttles the second call (observed flake).
        await asyncio.sleep(60.0 / 100_000 + 0.001)
        await client.get_db_info()
    assert calls == 2


@pytest.mark.asyncio
async def test_invalid_json_and_oversized_responses_fail_closed() -> None:
    async def invalid(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b"not-json", headers={"content-type": "application/json"}, request=request
        )

    client = MikrusClient(
        "https://api.mikr.us",
        "key",
        "srv",
        requests_per_minute=100_000,
        transport=httpx.MockTransport(invalid),
    )
    async with client:
        with pytest.raises(AppError, match="invalid JSON"):
            await client.get_server_info()

    async def oversized(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=json.dumps({"x": "a" * 1_000_001}).encode(), request=request
        )

    client = MikrusClient(
        "https://api.mikr.us",
        "key",
        "srv",
        requests_per_minute=100_000,
        transport=httpx.MockTransport(oversized),
    )
    async with client:
        with pytest.raises(AppError, match="size limit"):
            await client.get_server_info()


@pytest.mark.asyncio
async def test_read_retry_taxonomy_distinguishes_transient_rejected_and_protocol_failures() -> None:
    async def transient(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request)

    client = MikrusClient(
        "https://api.mikr.us",
        "key",
        "srv",
        requests_per_minute=100_000,
        transport=httpx.MockTransport(transient),
    )
    async with client:
        with pytest.raises(AppError) as caught:
            await client.get_server_info()
    assert caught.value.code is ErrorCode.TRANSIENT_UPSTREAM

    async def rejected(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, request=request)

    client = MikrusClient(
        "https://api.mikr.us",
        "key",
        "srv",
        requests_per_minute=100_000,
        transport=httpx.MockTransport(rejected),
    )
    async with client:
        with pytest.raises(AppError) as caught:
            await client.get_server_info()
    assert caught.value.code is ErrorCode.UPSTREAM_REJECTED

    async def invalid_json(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"not-json",
            headers={"content-type": "application/json"},
            request=request,
        )

    client = MikrusClient(
        "https://api.mikr.us",
        "key",
        "srv",
        requests_per_minute=100_000,
        transport=httpx.MockTransport(invalid_json),
    )
    async with client:
        with pytest.raises(AppError) as caught:
            await client.get_server_info()
    assert caught.value.code is ErrorCode.UPSTREAM_PROTOCOL


@pytest.mark.asyncio
async def test_mutation_timeout_and_5xx_are_ambiguous_but_preconnect_failure_is_not() -> None:
    async def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("response timed out", request=request)

    client = MikrusClient(
        "https://api.mikr.us",
        "key",
        "srv",
        requests_per_minute=100_000,
        transport=httpx.MockTransport(timeout),
    )
    async with client:
        with pytest.raises(AppError) as caught:
            await client.restart_server()
    assert caught.value.code is ErrorCode.AMBIGUOUS
    assert caught.value.retryable is False
    assert "reconcile" in caught.value.message

    async def failed_after_send(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request)

    client = MikrusClient(
        "https://api.mikr.us",
        "key",
        "srv",
        requests_per_minute=100_000,
        transport=httpx.MockTransport(failed_after_send),
    )
    async with client:
        with pytest.raises(AppError) as caught:
            await client.restart_server()
    assert caught.value.code is ErrorCode.AMBIGUOUS

    async def connect_failure(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connect failed", request=request)

    client = MikrusClient(
        "https://api.mikr.us",
        "key",
        "srv",
        requests_per_minute=100_000,
        transport=httpx.MockTransport(connect_failure),
    )
    async with client:
        with pytest.raises(AppError) as caught:
            await client.restart_server()
    assert caught.value.code is ErrorCode.TRANSIENT_UPSTREAM
