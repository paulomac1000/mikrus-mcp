from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

import pytest

from mikrus_mcp.approvals import ApprovalRegistry, normalized_arguments_digest
from mikrus_mcp.config import Settings, TargetConfig
from mikrus_mcp.kernel import CallerContext, InvocationKernel
from mikrus_mcp.manifests import MANIFESTS
from mikrus_mcp.targets import TargetRegistry


class SlowMutationClient:
    def __init__(self, config: TargetConfig) -> None:
        self.stable_identity = config.stable_identity
        self.started = asyncio.Event()

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def write_file(self, path: str, content: str) -> dict[str, object]:
        del path, content
        self.started.set()
        await asyncio.sleep(60)
        return {"output": "WRITE_OK"}


@pytest.mark.asyncio
async def test_mutation_deadline_after_execution_start_is_ambiguous() -> None:
    target = TargetConfig(
        "prod",
        "mikrus",
        api_url="https://api.mikr.us",
        api_key="k",
        server_id="srv",
    )
    settings = Settings(
        {"prod": target},
        "prod",
        write_enabled=True,
        default_deadline_ms=120_000,
        allowed_scopes=frozenset(
            {"tool:*", "target:*", "target-id:*", "resource:*", "data:*", "write:server"}
        ),
    )
    client = SlowMutationClient(target)
    registry = TargetRegistry(
        {"prod": target},
        factory=lambda _: client,  # type: ignore[arg-type]
    )
    approvals = ApprovalRegistry()
    arguments: dict[str, Any] = {"path": "/tmp/a", "content": "x"}
    digest = normalized_arguments_digest(arguments)
    approvals.issue_for_test(
        "write_file",
        "principal",
        target.stable_identity,
        "/tmp/a",
        digest,
    )
    kernel = InvocationKernel(settings, registry=registry, approvals=approvals)
    original = MANIFESTS["write_file"]
    MANIFESTS["write_file"] = replace(original, timeout_ms=100)
    try:
        result = await kernel.invoke(
            "write_file",
            arguments,
            CallerContext("principal", settings.allowed_scopes),
        )
    finally:
        MANIFESTS["write_file"] = original

    assert client.started.is_set()
    assert result["error"]["code"] == "AMBIGUOUS_OUTCOME"
    assert result["error"]["retryable"] is False
    assert not approvals.has_matching(
        "write_file",
        "principal",
        target.stable_identity,
        "/tmp/a",
        digest,
    )


@pytest.mark.asyncio
async def test_too_short_mutation_deadline_times_out_before_consuming_approval() -> None:
    target = TargetConfig(
        "prod",
        "mikrus",
        api_url="https://api.mikr.us",
        api_key="k",
        server_id="srv",
    )
    settings = Settings(
        {"prod": target},
        "prod",
        write_enabled=True,
        default_deadline_ms=120_000,
        allowed_scopes=frozenset(
            {"tool:*", "target:*", "target-id:*", "resource:*", "data:*", "write:server"}
        ),
    )
    client = SlowMutationClient(target)
    registry = TargetRegistry(
        {"prod": target},
        factory=lambda _: client,  # type: ignore[arg-type]
    )
    approvals = ApprovalRegistry()
    arguments: dict[str, Any] = {"path": "/tmp/a", "content": "x"}
    digest = normalized_arguments_digest(arguments)
    approvals.issue_for_test(
        "write_file",
        "principal",
        target.stable_identity,
        "/tmp/a",
        digest,
    )
    kernel = InvocationKernel(settings, registry=registry, approvals=approvals)

    result = await kernel.invoke(
        "write_file",
        arguments,
        CallerContext("principal", settings.allowed_scopes),
        deadline_ms=100,
    )

    assert not client.started.is_set()
    assert result["error"]["code"] == "TIMEOUT"
    assert approvals.has_matching(
        "write_file",
        "principal",
        target.stable_identity,
        "/tmp/a",
        digest,
    )
