from __future__ import annotations

import json

import httpx
import pytest

from mikrus_mcp.client import MikrusClient
from mikrus_mcp.errors import AppError, ErrorCode


@pytest.mark.asyncio
async def test_http_request_binds_credentials_and_target() -> None:
    observed: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return httpx.Response(200, json={"server_id": "srv"}, request=request)

    client = MikrusClient(
        "https://api.mikr.us",
        "key",
        "srv",
        requests_per_minute=100_000,
        transport=httpx.MockTransport(handler),
    )
    async with client:
        result = await client.get_server_info()
    assert result["server_id"] == "srv"
    assert observed[0].headers["authorization"] == "Bearer key"
    assert b"srv=srv" in observed[0].content and b"key=key" in observed[0].content


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
        return httpx.Response(200, json={"password": str(calls)}, request=request)

    client = MikrusClient(
        "https://api.mikr.us",
        "key",
        "srv",
        requests_per_minute=100_000,
        transport=httpx.MockTransport(handler),
    )
    async with client:
        await client.get_db_info()
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
