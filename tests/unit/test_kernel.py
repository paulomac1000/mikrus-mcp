from __future__ import annotations

import asyncio
from typing import Any

import pytest

from mikrus_mcp.config import Settings, TargetConfig
from mikrus_mcp.errors import AppError, ErrorCode
from mikrus_mcp.kernel import ApprovalRegistry, CallerContext, InvocationKernel, TargetRegistry
from mikrus_mcp.manifests import MANIFESTS


class MockMikrusClient:
    def __init__(self, config: TargetConfig, *, fail_open: bool = False) -> None:
        self.config = config
        self.stable_identity = config.stable_identity
        self.fail_open = fail_open
        self.opened = False
        self.closed = False
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    async def open(self) -> None:
        if self.fail_open:
            raise ConnectionError("offline")
        self.opened = True

    async def close(self) -> None:
        self.closed = True

    async def get_server_info(self) -> dict[str, object]:
        self.calls.append(("get_server_info", ()))
        return {"server_id": self.config.server_id, "password": "must-redact"}

    async def write_file(self, path: str, content: str) -> dict[str, object]:
        self.calls.append(("write_file", (path, content)))
        return {"output": "WRITE_OK"}

    async def execute_command(self, cmd: str) -> dict[str, object]:
        self.calls.append(("execute_command", (cmd,)))
        return {"output": "ok"}


@pytest.fixture
def target() -> TargetConfig:
    return TargetConfig(
        "prod", "mikrus", api_url="https://api.mikr.us", api_key="k", server_id="srv"
    )


def make_settings(target: TargetConfig, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "targets": {"prod": target},
        "default_target": "prod",
        "allowed_scopes": frozenset({"tool:*", "target:*", "write:server"}),
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.asyncio
async def test_authorization_happens_before_network_resolution(target: TargetConfig) -> None:
    calls = 0

    def factory(config: TargetConfig) -> MockMikrusClient:
        nonlocal calls
        calls += 1
        return MockMikrusClient(config)

    registry = TargetRegistry({"prod": target}, factory=factory)  # type: ignore[arg-type]
    kernel = InvocationKernel(make_settings(target), registry=registry)
    result = await kernel.invoke(
        "get_server_info",
        {"server": "prod"},
        CallerContext("principal", frozenset()),
    )
    assert result["error"]["code"] == "AUTHORIZATION_FAILED"
    assert calls == 0


@pytest.mark.asyncio
async def test_default_target_failure_does_not_fallback(target: TargetConfig) -> None:
    backup = TargetConfig(
        "backup", "mikrus", api_url="https://api.mikr.us", api_key="k", server_id="backup"
    )

    def factory(config: TargetConfig) -> MockMikrusClient:
        return MockMikrusClient(config, fail_open=config.name == "prod")

    settings = Settings(
        {"prod": target, "backup": backup},
        "prod",
        allowed_scopes=frozenset({"tool:*", "target:*"}),
    )
    registry = TargetRegistry(dict(settings.targets), factory=factory)  # type: ignore[arg-type]
    result = await InvocationKernel(settings, registry=registry).invoke(
        "get_server_info", {}, CallerContext("principal", settings.allowed_scopes)
    )
    assert result["error"]["code"] == "UNAVAILABLE"
    assert registry.status("prod")["targets"][1]["status"] == "not_connected"


@pytest.mark.asyncio
async def test_read_result_is_field_sanitized(target: TargetConfig) -> None:
    client = MockMikrusClient(target)
    registry = TargetRegistry({"prod": target}, factory=lambda _: client)  # type: ignore[arg-type]
    settings = make_settings(target)
    result = await InvocationKernel(settings, registry=registry).invoke(
        "get_server_info", {}, CallerContext("principal", settings.allowed_scopes)
    )
    assert result["success"] is True
    assert result["data"]["password"] == "<REDACTED>"
    assert result["_meta"]["target"] == "prod"


@pytest.mark.asyncio
async def test_write_requires_operator_gate_and_one_time_approval(target: TargetConfig) -> None:
    client = MockMikrusClient(target)
    registry = TargetRegistry({"prod": target}, factory=lambda _: client)  # type: ignore[arg-type]
    approvals = ApprovalRegistry()
    disabled = make_settings(target, write_enabled=False)
    caller = CallerContext("principal", disabled.allowed_scopes)
    denied = await InvocationKernel(disabled, registry=registry, approvals=approvals).invoke(
        "write_file", {"path": "/tmp/a", "content": "x"}, caller
    )
    assert denied["error"]["code"] == "AUTHORIZATION_FAILED"
    assert not client.calls

    enabled = make_settings(target, write_enabled=True)
    kernel = InvocationKernel(enabled, registry=registry, approvals=approvals)
    no_token = await kernel.invoke("write_file", {"path": "/tmp/a", "content": "x"}, caller)
    assert no_token["error"]["code"] == "AUTHORIZATION_FAILED"
    approvals.issue_for_test("write_file", "principal", target.stable_identity, "/tmp/a")
    approved = await kernel.invoke(
        "write_file",
        {"path": "/tmp/a", "content": "x"},
        CallerContext("principal", enabled.allowed_scopes),
    )
    assert approved["success"] is True
    replay = await kernel.invoke(
        "write_file",
        {"path": "/tmp/a", "content": "x"},
        CallerContext("principal", enabled.allowed_scopes),
    )
    assert replay["error"]["code"] == "AUTHORIZATION_FAILED"
    assert client.calls == [("write_file", ("/tmp/a", "x"))]


@pytest.mark.asyncio
async def test_command_profile_is_inactive_by_default(target: TargetConfig) -> None:
    settings = make_settings(target, write_enabled=True, command_execution_enabled=False)
    kernel = InvocationKernel(settings)
    result = await kernel.invoke(
        "execute_command",
        {"cmd": "uptime"},
        CallerContext("principal", settings.allowed_scopes),
    )
    assert result["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_cancellation_is_not_swallowed(target: TargetConfig) -> None:
    class SlowClient(MockMikrusClient):
        async def get_server_info(self) -> dict[str, object]:
            await asyncio.sleep(60)
            return {}

    settings = make_settings(target, default_deadline_ms=120_000)
    registry = TargetRegistry(
        {"prod": target},
        factory=lambda _: SlowClient(target),  # type: ignore[arg-type]
    )
    kernel = InvocationKernel(settings, registry=registry)
    task = asyncio.create_task(
        kernel.invoke("get_server_info", {}, CallerContext("principal", settings.allowed_scopes))
    )
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_validation_happens_before_approval_consumption(target: TargetConfig) -> None:
    client = MockMikrusClient(target)
    registry = TargetRegistry({"prod": target}, factory=lambda _: client)  # type: ignore[arg-type]
    approvals = ApprovalRegistry()
    settings = make_settings(target, write_enabled=True)
    kernel = InvocationKernel(settings, registry=registry, approvals=approvals)
    approvals.issue_for_test("write_file", "principal", target.stable_identity, "/tmp/a")
    caller = CallerContext("principal", settings.allowed_scopes)

    invalid = await kernel.invoke("write_file", {"path": "/etc/passwd", "content": "x"}, caller)
    assert invalid["error"]["code"] == "VALIDATION_FAILED"
    assert client.calls == []

    approved = await kernel.invoke("write_file", {"path": "/tmp/a", "content": "x"}, caller)
    assert approved["success"] is True


@pytest.mark.asyncio
async def test_manifest_controls_read_retry_but_mutation_is_single_attempt(
    target: TargetConfig,
) -> None:
    class RateLimitedClient(MockMikrusClient):
        def __init__(self, config: TargetConfig) -> None:
            super().__init__(config)
            self.read_attempts = 0
            self.write_attempts = 0

        async def get_server_info(self) -> dict[str, object]:
            self.read_attempts += 1
            if self.read_attempts == 1:
                raise AppError(
                    ErrorCode.RATE_LIMITED,
                    "retry later",
                    retry_after_seconds=0,
                )
            return {"server_id": "srv"}

        async def write_file(self, path: str, content: str) -> dict[str, object]:
            self.write_attempts += 1
            raise AppError(
                ErrorCode.RATE_LIMITED,
                "do not retry mutation",
                retry_after_seconds=0,
            )

    client = RateLimitedClient(target)
    registry = TargetRegistry({"prod": target}, factory=lambda _: client)  # type: ignore[arg-type]
    approvals = ApprovalRegistry()
    settings = make_settings(target, write_enabled=True)
    kernel = InvocationKernel(settings, registry=registry, approvals=approvals)

    async def no_sleep(_: float) -> None:
        return None

    kernel._sleep = no_sleep
    read = await kernel.invoke(
        "get_server_info",
        {},
        CallerContext("principal", settings.allowed_scopes),
    )
    assert read["success"] is True
    assert client.read_attempts == 2

    approvals.issue_for_test("write_file", "principal", target.stable_identity, "/tmp/a")
    write = await kernel.invoke(
        "write_file",
        {"path": "/tmp/a", "content": "x"},
        CallerContext("principal", settings.allowed_scopes),
    )
    assert write["error"]["code"] == "RATE_LIMITED"
    assert write["error"]["retryable"] is False
    assert client.write_attempts == 1


@pytest.mark.asyncio
async def test_approval_is_not_consumed_while_waiting_for_lock(
    target: TargetConfig,
) -> None:
    client = MockMikrusClient(target)
    registry = TargetRegistry({"prod": target}, factory=lambda _: client)  # type: ignore[arg-type]
    approvals = ApprovalRegistry()
    settings = make_settings(target, write_enabled=True, default_deadline_ms=100)
    kernel = InvocationKernel(settings, registry=registry, approvals=approvals)
    approvals.issue_for_test("write_file", "principal", target.stable_identity, "/tmp/a")
    arguments = {"path": "/tmp/a", "content": "x"}
    lock = kernel._lock_for(MANIFESTS["write_file"], "prod", arguments)
    assert lock is not None
    await lock.acquire()
    try:
        result = await kernel.invoke(
            "write_file",
            arguments,
            CallerContext("principal", settings.allowed_scopes),
        )
    finally:
        lock.release()
    assert result["error"]["code"] == "TIMEOUT"
    assert approvals.has_matching("write_file", "principal", target.stable_identity, "/tmp/a")


@pytest.mark.asyncio
async def test_mikrus_target_type_is_rejected_before_connection() -> None:
    target = TargetConfig("ssh", "ssh", host="server.example")
    factory_calls = 0

    def factory(config: TargetConfig) -> MockMikrusClient:
        nonlocal factory_calls
        factory_calls += 1
        return MockMikrusClient(config)

    settings = Settings(
        {"ssh": target},
        "ssh",
        allowed_scopes=frozenset({"tool:*", "target:*"}),
    )
    registry = TargetRegistry({"ssh": target}, factory=factory)  # type: ignore[arg-type]
    result = await InvocationKernel(settings, registry=registry).invoke(
        "get_server_info",
        {},
        CallerContext("principal", settings.allowed_scopes),
    )
    assert result["error"]["code"] == "VALIDATION_FAILED"
    assert factory_calls == 0


@pytest.mark.asyncio
async def test_approval_is_not_consumed_when_target_connection_fails(
    target: TargetConfig,
) -> None:
    registry = TargetRegistry(
        {"prod": target},
        factory=lambda config: MockMikrusClient(config, fail_open=True),  # type: ignore[arg-type]
    )
    approvals = ApprovalRegistry()
    settings = make_settings(target, write_enabled=True)
    approvals.issue_for_test("write_file", "principal", target.stable_identity, "/tmp/a")
    result = await InvocationKernel(
        settings,
        registry=registry,
        approvals=approvals,
    ).invoke(
        "write_file",
        {"path": "/tmp/a", "content": "x"},
        CallerContext("principal", settings.allowed_scopes),
    )
    assert result["error"]["code"] == "UNAVAILABLE"
    assert approvals.has_matching("write_file", "principal", target.stable_identity, "/tmp/a")
