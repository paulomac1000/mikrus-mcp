from __future__ import annotations

import asyncio
from typing import Any

import pytest

from mikrus_mcp.approvals import normalized_arguments_digest
from mikrus_mcp.config import Settings, TargetConfig
from mikrus_mcp.errors import AppError, ErrorCode
from mikrus_mcp.kernel import ApprovalRegistry, CallerContext, InvocationKernel, TargetRegistry
from mikrus_mcp.manifests import MANIFESTS


def mikrus_info_payload() -> dict[str, object]:
    return {
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


def mikrus_db_payload() -> dict[str, object]:
    return {
        "db_user": "abc123",
        "db_host": "db.mikr.us",
        "db_port": "3306",
        "db_name": "abc123",
        "password": "redacted-secret",
    }


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
        return mikrus_info_payload()

    async def get_db_info(self) -> dict[str, object]:
        self.calls.append(("get_db_info", ()))
        return mikrus_db_payload()

    async def write_file(self, path: str, content: str) -> dict[str, object]:
        self.calls.append(("write_file", (path, content)))
        return {"output": "WRITE_OK"}


@pytest.fixture
def target() -> TargetConfig:
    return TargetConfig(
        "prod", "mikrus", api_url="https://api.mikr.us", api_key="k", server_id="srv"
    )


def make_settings(target: TargetConfig, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "targets": {"prod": target},
        "default_target": "prod",
        "allowed_scopes": frozenset(
            {"tool:*", "target:*", "target-id:*", "resource:*", "data:*", "write:server"}
        ),
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
        allowed_scopes=frozenset({"tool:*", "target:*", "target-id:*", "resource:*", "data:*"}),
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
        "get_db_info", {}, CallerContext("principal", settings.allowed_scopes)
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
    disabled_kernel = InvocationKernel(disabled, registry=registry, approvals=approvals)
    assert "write_file" not in disabled_kernel.active_names
    denied = await disabled_kernel.invoke("write_file", {"path": "/tmp/a", "content": "x"}, caller)
    assert denied["error"]["code"] == "NOT_FOUND"
    assert not client.calls

    enabled = make_settings(target, write_enabled=True)
    kernel = InvocationKernel(enabled, registry=registry, approvals=approvals)
    no_token = await kernel.invoke("write_file", {"path": "/tmp/a", "content": "x"}, caller)
    assert no_token["error"]["code"] == "AUTHORIZATION_FAILED"
    approvals.issue_for_test(
        "write_file",
        "principal",
        target.stable_identity,
        "/tmp/a",
        normalized_arguments_digest({"path": "/tmp/a", "content": "x"}),
    )
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
async def test_general_purpose_command_capability_is_absent(target: TargetConfig) -> None:
    settings = make_settings(target, write_enabled=True)
    kernel = InvocationKernel(settings)
    assert "execute_command" not in kernel.active_names
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
            return mikrus_info_payload()

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
    approvals.issue_for_test(
        "write_file",
        "principal",
        target.stable_identity,
        "/tmp/a",
        normalized_arguments_digest({"path": "/tmp/a", "content": "x"}),
    )
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
            return mikrus_info_payload()

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

    approvals.issue_for_test(
        "write_file",
        "principal",
        target.stable_identity,
        "/tmp/a",
        normalized_arguments_digest({"path": "/tmp/a", "content": "x"}),
    )
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
    approvals.issue_for_test(
        "write_file",
        "principal",
        target.stable_identity,
        "/tmp/a",
        normalized_arguments_digest({"path": "/tmp/a", "content": "x"}),
    )
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
    assert approvals.has_matching(
        "write_file",
        "principal",
        target.stable_identity,
        "/tmp/a",
        normalized_arguments_digest({"path": "/tmp/a", "content": "x"}),
    )


@pytest.mark.asyncio
async def test_mikrus_target_type_is_rejected_before_connection() -> None:
    mikrus = TargetConfig(
        "prod", "mikrus", api_url="https://api.mikr.us", api_key="k", server_id="srv"
    )
    ssh = TargetConfig("ssh", "ssh", host="server.example")
    factory_calls = 0

    def factory(config: TargetConfig) -> MockMikrusClient:
        nonlocal factory_calls
        factory_calls += 1
        return MockMikrusClient(config)

    settings = Settings(
        {"prod": mikrus, "ssh": ssh},
        "prod",
        allowed_scopes=frozenset({"tool:*", "target:*", "target-id:*", "resource:*", "data:*"}),
    )
    registry = TargetRegistry(dict(settings.targets), factory=factory)  # type: ignore[arg-type]
    result = await InvocationKernel(settings, registry=registry).invoke(
        "get_server_info",
        {"server": "ssh"},
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
    approvals.issue_for_test(
        "write_file",
        "principal",
        target.stable_identity,
        "/tmp/a",
        normalized_arguments_digest({"path": "/tmp/a", "content": "x"}),
    )
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
    assert approvals.has_matching(
        "write_file",
        "principal",
        target.stable_identity,
        "/tmp/a",
        normalized_arguments_digest({"path": "/tmp/a", "content": "x"}),
    )


@pytest.mark.asyncio
async def test_kernel_retries_only_explicit_transient_upstream_errors(target: TargetConfig) -> None:
    class ClassifiedClient(MockMikrusClient):
        def __init__(self, config: TargetConfig, code: ErrorCode) -> None:
            super().__init__(config)
            self.code = code
            self.attempts = 0

        async def get_server_info(self) -> dict[str, object]:
            self.attempts += 1
            if self.attempts == 1:
                raise AppError(self.code, "classified failure")
            return mikrus_info_payload()

    settings = make_settings(target)
    caller = CallerContext("principal", settings.allowed_scopes)

    transient = ClassifiedClient(target, ErrorCode.TRANSIENT_UPSTREAM)
    transient_registry = TargetRegistry(
        {"prod": target},
        factory=lambda _: transient,  # type: ignore[arg-type]
    )
    transient_kernel = InvocationKernel(settings, registry=transient_registry)

    async def no_sleep(_: float) -> None:
        return None

    transient_kernel._sleep = no_sleep
    result = await transient_kernel.invoke("get_server_info", {}, caller)
    assert result["success"] is True
    assert transient.attempts == 2

    for code in (ErrorCode.UPSTREAM_PROTOCOL, ErrorCode.UPSTREAM_REJECTED, ErrorCode.UPSTREAM):
        permanent = ClassifiedClient(target, code)
        permanent_registry = TargetRegistry(
            {"prod": target},
            factory=lambda _, client=permanent: client,  # type: ignore[arg-type]
        )
        permanent_kernel = InvocationKernel(settings, registry=permanent_registry)
        permanent_kernel._sleep = no_sleep
        result = await permanent_kernel.invoke("get_server_info", {}, caller)
        assert result["success"] is False
        assert result["error"]["code"] == code.value
        assert permanent.attempts == 1
