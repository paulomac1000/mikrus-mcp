"""Regression coverage for the audit hardening pass.

Each test pins one invariant that the ai-skills@main authority requires: authorization
ordering, resolved identity, readiness semantics, manifest/runtime parity, error provenance,
and bounded retry backoff inside the operation deadline.
"""

from __future__ import annotations

import pytest

from mikrus_mcp.approvals import ApprovalRegistry
from mikrus_mcp.config import Settings, TargetConfig
from mikrus_mcp.errors import AppError, ErrorCode
from mikrus_mcp.kernel import CallerContext, InvocationKernel
from mikrus_mcp.manifests import MANIFESTS
from mikrus_mcp.targets import TargetRegistry

INFO_PAYLOAD: dict[str, object] = {
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


class StubClient:
    def __init__(self, config: TargetConfig) -> None:
        self.stable_identity = config.stable_identity
        self.fail_reads = False
        self.reads = 0

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def get_server_info(self) -> dict[str, object]:
        self.reads += 1
        if self.fail_reads:
            raise AppError(ErrorCode.UPSTREAM, "upstream exploded")
        return INFO_PAYLOAD


def make_kernel(
    target: TargetConfig,
    client: StubClient,
    *,
    scopes: frozenset[str] | None = None,
) -> InvocationKernel:
    settings = Settings(
        {target.name: target},
        target.name,
        allowed_scopes=scopes
        or frozenset(
            {
                "tool:*",
                "target:*",
                "target-id:*",
                "resource:*",
                "data:*",
                "target:srv",
                "write:server",
            }
        ),
    )
    registry = TargetRegistry({target.name: target}, factory=lambda _: client)  # type: ignore[arg-type]
    return InvocationKernel(settings, registry=registry, approvals=ApprovalRegistry())


@pytest.mark.asyncio
async def test_unauthorized_caller_cannot_probe_target_existence() -> None:
    target = TargetConfig(
        "prod", "mikrus", api_url="https://api.mikr.us", api_key="k", server_id="srv"
    )
    kernel = make_kernel(
        target,
        StubClient(target),
        scopes=frozenset({"tool:get_server_info", "data:internal"}),
    )
    caller = CallerContext("principal", kernel.settings.allowed_scopes)
    denied = await kernel.invoke("get_server_info", {"server": "hidden-target"}, caller)
    assert denied["error"]["code"] == "AUTHORIZATION_FAILED"
    assert "unknown target" not in str(denied["error"]["message"])

    insider = CallerContext(
        "principal",
        frozenset({"tool:*", "target:*", "target-id:*", "resource:*", "data:*"}),
    )
    missing = await kernel.invoke("get_server_info", {"server": "hidden-target"}, insider)
    assert missing["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_resolved_target_identity_requires_post_resolution_authorization() -> None:
    target = TargetConfig(
        "prod", "mikrus", api_url="https://api.mikr.us", api_key="k", server_id="srv"
    )
    client = StubClient(target)
    kernel = make_kernel(
        target,
        client,
        scopes=frozenset(
            {
                "tool:get_server_info",
                "target:prod",
                "target-id:mikrus:other",
                "data:internal",
            }
        ),
    )
    result = await kernel.invoke(
        "get_server_info",
        {},
        CallerContext("principal", kernel.settings.allowed_scopes),
    )
    assert result["error"]["code"] == "AUTHORIZATION_FAILED"
    assert client.reads == 0


@pytest.mark.asyncio
async def test_data_classification_is_authorized_before_target_resolution() -> None:
    target = TargetConfig(
        "prod", "mikrus", api_url="https://api.mikr.us", api_key="k", server_id="srv"
    )
    client = StubClient(target)
    kernel = make_kernel(
        target,
        client,
        scopes=frozenset({"tool:get_server_info", "target:prod", "target-id:*"}),
    )
    result = await kernel.invoke(
        "get_server_info",
        {},
        CallerContext("principal", kernel.settings.allowed_scopes),
    )
    assert result["error"]["code"] == "AUTHORIZATION_FAILED"
    assert client.reads == 0
    assert kernel.registry.resolved_identity("prod") is None


@pytest.mark.asyncio
async def test_error_responses_carry_resolved_provenance() -> None:
    target = TargetConfig(
        "prod", "mikrus", api_url="https://api.mikr.us", api_key="k", server_id="srv"
    )
    client = StubClient(target)
    client.fail_reads = True
    kernel = make_kernel(target, client)
    caller = CallerContext("principal", kernel.settings.allowed_scopes)

    failed = await kernel.invoke("get_server_info", {}, caller)
    meta = failed["_meta"]
    assert meta["capability"] == "get_server_info"
    assert meta["capability_version"]
    assert meta["target"] == "prod"
    assert meta["target_identity"] == target.stable_identity
    assert meta["backend"] == "mikrus"

    unknown = await kernel.invoke("no_such_capability", {}, caller)
    assert "_meta" in unknown
    assert "target" not in unknown["_meta"]
    assert "backend" not in unknown["_meta"]


def test_readiness_requires_connected_default_target() -> None:
    target = TargetConfig(
        "prod", "mikrus", api_url="https://api.mikr.us", api_key="k", server_id="srv"
    )
    kernel = make_kernel(target, StubClient(target))
    health = kernel.health()
    assert health["ready"] is False
    assert health["readiness_reason"] == "default target is not_connected"


def test_manifest_projection_matches_runtime_enforcement() -> None:
    for _name, manifest in MANIFESTS.items():
        projection = manifest.as_dict()
        concurrency = projection["concurrency"]
        assert isinstance(concurrency, dict)
        if manifest.concurrent_safe:
            assert concurrency == {"scope": "none", "serialized": False}
        else:
            assert concurrency["serialized"] is True
            assert concurrency["limit"] == 1
            assert concurrency["scope"] == manifest.concurrency_scope
        assert "queue_limit" not in concurrency
        extensions = projection["extensions"]
        assert extensions["operational_impact"] == manifest.operational_impact
        assert extensions["idempotency_mechanism"] == manifest.idempotency_mechanism
        approval = projection.get("approval")
        if manifest.requires_approval:
            assert approval is not None
            assert approval["record_ttl_seconds_default"] == 60
            assert approval["record_ttl_seconds_max"] == 300
            assert "resource" in approval["binds"]
        else:
            assert approval is None


@pytest.mark.asyncio
async def test_retry_backoff_cannot_outlive_the_operation_deadline() -> None:
    target = TargetConfig(
        "prod", "mikrus", api_url="https://api.mikr.us", api_key="k", server_id="srv"
    )

    class AlwaysRateLimited(StubClient):
        async def get_server_info(self) -> dict[str, object]:
            raise AppError(
                ErrorCode.RATE_LIMITED,
                "slow down",
                retry_after_seconds=50.0,
            )

    kernel = make_kernel(target, AlwaysRateLimited(target))

    async def no_sleep(_: float) -> None:
        return None

    kernel._sleep = no_sleep
    result = await kernel.invoke(
        "get_server_info",
        {},
        CallerContext("principal", kernel.settings.allowed_scopes),
        deadline_ms=1000,
    )
    assert result["error"]["code"] == "RATE_LIMITED"
    assert result["error"]["retryable"] is True
    assert result["error"]["retry_after_seconds"] == 50.0
