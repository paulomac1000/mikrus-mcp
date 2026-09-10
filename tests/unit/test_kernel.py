from __future__ import annotations

import asyncio
from pathlib import Path
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


def _ssh_target() -> TargetConfig:
    return TargetConfig("host", "ssh", host="server.example")


def _mikrus_target() -> TargetConfig:
    return TargetConfig(
        "prod", "mikrus", api_url="https://api.mikr.us", api_key="k", server_id="srv"
    )


class FakeSshJobsClient:
    """Kernel-level double for the SSH-backed file patch and cron capabilities."""

    def __init__(self, config: TargetConfig) -> None:
        self.config = config
        self.stable_identity = f"{config.stable_identity}#host-key=SHA256:test-host-key"
        self.crontab = "# user entry\n0 0 * * * existing-job\n"
        self.installs: list[str] = []
        self.patches: list[dict[str, str]] = []
        self.install_fails_concurrently = False

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def cron_read(self) -> dict[str, object]:
        import hashlib

        encoded = self.crontab.encode("utf-8")
        return {
            "text": self.crontab,
            "hash": hashlib.sha256(encoded).hexdigest(),
            "size": len(encoded),
        }

    async def cron_install(self, *, expected_hash: str, new_text: str) -> dict[str, object]:
        import hashlib

        if (
            self.install_fails_concurrently
            or hashlib.sha256(self.crontab.encode("utf-8")).hexdigest() != expected_hash
        ):
            raise AppError(
                ErrorCode.CONFLICT,
                "the installed crontab changed concurrently (CONCURRENT_MODIFICATION)",
            )
        self.installs.append(new_text)
        self.crontab = new_text
        return {"status": "INSTALLED", "hash": expected_hash, "size": len(new_text)}

    async def file_patch_atomic(
        self, *, path: str, expected_digest: str, content_b64: str
    ) -> dict[str, object]:
        self.patches.append(
            {
                "path": path,
                "expected_digest": expected_digest,
                "content_b64": content_b64,
            }
        )
        return {"status": "REPLACED", "before_size": 1, "after_size": 2}


def _cron_settings(
    ssh_client: FakeSshJobsClient,
    *,
    store_file: Any = None,
    write_enabled: bool = False,
) -> Settings:
    targets: dict[str, TargetConfig] = {"host": _ssh_target()}
    values: dict[str, Any] = {
        "targets": targets,
        "default_target": "host",
        "allowed_scopes": frozenset(
            {"tool:*", "target:*", "target-id:*", "resource:*", "data:*", "write:server"}
        ),
        "write_enabled": write_enabled,
    }
    if store_file is not None:
        values["cron_profile_store_file"] = store_file
    settings = Settings(**values)
    return settings


def _kernel_for(
    settings: Settings, client: FakeSshJobsClient, approvals: ApprovalRegistry | None = None
) -> InvocationKernel:
    registry = TargetRegistry(
        dict(settings.targets),
        factory=lambda _: client,  # type: ignore[arg-type]
    )
    return InvocationKernel(settings, registry=registry, approvals=approvals)


def _schedule() -> dict[str, str]:
    return {
        "minute": "0",
        "hour": "3",
        "day_of_month": "*",
        "month": "*",
        "day_of_week": "1-5",
    }


@pytest.mark.asyncio
async def test_cron_and_patch_capabilities_fail_closed_without_store(tmp_path: Path) -> None:
    client = FakeSshJobsClient(_ssh_target())
    settings = _cron_settings(client, write_enabled=True)
    from mikrus_mcp.manifests import active_names, inactive_reason

    assert "cron_list" not in active_names(settings)
    assert "cron_upsert" not in active_names(settings)
    assert "cron_remove" not in active_names(settings)
    assert inactive_reason("cron_list", settings) == {
        "code": "STORE_NOT_CONFIGURED",
        "message": "requires MCP_CRON_PROFILE_STORE_FILE",
    }
    assert "file_patch_atomic" in active_names(settings)

    kernel = _kernel_for(settings, client)
    result = await kernel.invoke(
        "cron_list", {}, CallerContext("principal", settings.allowed_scopes)
    )
    assert result["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_cron_capabilities_activate_only_with_store(tmp_path: Path) -> None:
    from mikrus_mcp.manifests import active_names

    client = FakeSshJobsClient(_ssh_target())
    settings = _cron_settings(client, store_file=tmp_path / "cron.json", write_enabled=True)
    assert {"cron_list", "cron_upsert", "cron_remove"}.issubset(active_names(settings))


@pytest.mark.asyncio
async def test_mikrus_targets_report_unavailable_for_new_ssh_capabilities() -> None:
    client = FakeSshJobsClient(_ssh_target())
    targets = {"prod": _mikrus_target(), "host": _ssh_target()}
    settings = Settings(
        targets=targets,
        default_target="host",
        allowed_scopes=frozenset(
            {"tool:*", "target:*", "target-id:*", "resource:*", "data:*", "write:server"}
        ),
        write_enabled=True,
        cron_profile_store_file=Path("/tmp/unused-cron-store.json"),
        remote_job_store_file=Path("/tmp/unused-job-store.json"),
    )
    kernel = _kernel_for(settings, client)
    caller = CallerContext("principal", settings.allowed_scopes)

    patch = await kernel.invoke(
        "file_patch_atomic",
        {
            "server": "prod",
            "path": "/tmp/f",
            "expected_digest": "sha256:" + "a" * 64,
            "content_b64": "",
        },
        caller,
    )
    assert patch["error"]["code"] == "UNAVAILABLE"
    listing = await kernel.invoke("cron_list", {"server": "prod"}, caller)
    assert listing["error"]["code"] == "UNAVAILABLE"
    assert not client.patches


@pytest.mark.asyncio
async def test_cron_upsert_requires_approval_then_is_idempotent(tmp_path: Path) -> None:
    client = FakeSshJobsClient(_ssh_target())
    settings = _cron_settings(client, store_file=tmp_path / "cron.json", write_enabled=True)
    approvals = ApprovalRegistry()
    kernel = _kernel_for(settings, client, approvals)
    caller = CallerContext("principal", settings.allowed_scopes)
    arguments = {
        "profile_id": "backup",
        "schedule": _schedule(),
        "executable": "grep",
        "argv": ["--count"],
        "environment": {"LC_ALL": "C"},
    }

    denied = await kernel.invoke("cron_upsert", arguments, caller)
    assert denied["error"]["code"] == "AUTHORIZATION_FAILED"
    assert not client.installs

    approvals.issue_for_test(
        "cron_upsert",
        "principal",
        client.stable_identity,
        "backup",
        normalized_arguments_digest(arguments),
    )
    first = await kernel.invoke("cron_upsert", arguments, caller)
    assert first["success"] is True
    assert first["data"]["state"] == "IN_SYNC"
    assert client.crontab.count("# mikrus-mcp:backup:sha256=") == 1

    before = client.crontab
    approvals.issue_for_test(
        "cron_upsert",
        "principal",
        client.stable_identity,
        "backup",
        normalized_arguments_digest(arguments),
    )
    second = await kernel.invoke("cron_upsert", arguments, caller)
    assert second["success"] is True
    assert client.crontab == before
    assert client.crontab.count("# mikrus-mcp:backup:sha256=") == 1


@pytest.mark.asyncio
async def test_cron_remove_deletes_exactly_one_pair(tmp_path: Path) -> None:
    client = FakeSshJobsClient(_ssh_target())
    settings = _cron_settings(client, store_file=tmp_path / "cron.json", write_enabled=True)
    approvals = ApprovalRegistry()
    kernel = _kernel_for(settings, client, approvals)
    caller = CallerContext("principal", settings.allowed_scopes)

    for profile_id in ("backup", "other"):
        arguments = {
            "profile_id": profile_id,
            "schedule": _schedule(),
            "executable": "grep",
            "argv": [f"--{profile_id}"],
            "environment": {},
        }
        approvals.issue_for_test(
            "cron_upsert",
            "principal",
            client.stable_identity,
            profile_id,
            normalized_arguments_digest(arguments),
        )
        outcome = await kernel.invoke("cron_upsert", arguments, caller)
        assert outcome["success"] is True

    remove_arguments = {"profile_id": "backup"}
    approvals.issue_for_test(
        "cron_remove",
        "principal",
        client.stable_identity,
        "backup",
        normalized_arguments_digest(remove_arguments),
    )
    removed = await kernel.invoke("cron_remove", remove_arguments, caller)
    assert removed["success"] is True
    assert "mikrus-mcp:backup" not in client.crontab
    assert "--backup" not in client.crontab
    assert "mikrus-mcp:other" in client.crontab
    assert "# user entry\n" in client.crontab

    absent = {"profile_id": "absent"}
    approvals.issue_for_test(
        "cron_remove",
        "principal",
        client.stable_identity,
        "absent",
        normalized_arguments_digest(absent),
    )
    missing = await kernel.invoke("cron_remove", absent, caller)
    assert missing["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_cron_concurrent_modification_surfaces_conflict(tmp_path: Path) -> None:
    client = FakeSshJobsClient(_ssh_target())
    client.install_fails_concurrently = True
    settings = _cron_settings(client, store_file=tmp_path / "cron.json", write_enabled=True)
    approvals = ApprovalRegistry()
    kernel = _kernel_for(settings, client, approvals)
    caller = CallerContext("principal", settings.allowed_scopes)
    arguments = {
        "profile_id": "backup",
        "schedule": _schedule(),
        "executable": "grep",
        "argv": [],
        "environment": {},
    }
    approvals.issue_for_test(
        "cron_upsert",
        "principal",
        client.stable_identity,
        "backup",
        normalized_arguments_digest(arguments),
    )
    result = await kernel.invoke("cron_upsert", arguments, caller)
    assert result["error"]["code"] == "CONFLICT"
    assert not client.installs


@pytest.mark.asyncio
async def test_file_patch_atomic_end_to_end_is_typed_and_approved(tmp_path: Path) -> None:
    client = FakeSshJobsClient(_ssh_target())
    settings = _cron_settings(client, write_enabled=True)
    approvals = ApprovalRegistry()
    kernel = _kernel_for(settings, client, approvals)
    caller = CallerContext("principal", settings.allowed_scopes)
    arguments = {
        "path": "/tmp/srv/config.txt",
        "expected_digest": "sha256:" + "a" * 64,
        "content_b64": "SGVsbG8=",
    }

    denied = await kernel.invoke("file_patch_atomic", arguments, caller)
    assert denied["error"]["code"] == "AUTHORIZATION_FAILED"
    assert not client.patches

    approvals.issue_for_test(
        "file_patch_atomic",
        "principal",
        client.stable_identity,
        "/tmp/srv/config.txt",
        normalized_arguments_digest(arguments),
    )
    outcome = await kernel.invoke("file_patch_atomic", arguments, caller)
    assert outcome["success"] is True
    assert outcome["data"]["status"] == "REPLACED"
    assert client.patches == [arguments]


@pytest.mark.asyncio
async def test_file_patch_atomic_rejects_bad_digest_format_before_io() -> None:
    client = FakeSshJobsClient(_ssh_target())
    settings = _cron_settings(client, write_enabled=True)
    kernel = _kernel_for(settings, client)
    result = await kernel.invoke(
        "file_patch_atomic",
        {
            "path": "/tmp/f",
            "expected_digest": "md5:not-a-digest",
            "content_b64": "",
        },
        CallerContext("principal", settings.allowed_scopes),
    )
    assert result["error"]["code"] == "VALIDATION_FAILED"
    assert not client.patches


class FakeDockerComposeClient:
    """Kernel-level double for the Docker/Compose capability family."""

    def __init__(self, config: TargetConfig) -> None:
        self.config = config
        self.stable_identity = f"{config.stable_identity}#host-key=SHA256:dk"
        self.image_digest = "sha256:" + "9" * 64
        self.ups: list[dict[str, object]] = []
        self.waits: list[dict[str, object]] = []
        self.converged = False
        self.compose_cfg: dict[str, object] = {"services": {"web": {"image": "nginx:1.27"}}}
        self.ps_entries: list[dict[str, object]] = [
            {
                "ID": "abc123def0",
                "Names": ["/site-web-1"],
                "Labels": (
                    "com.docker.compose.project=site,"
                    "com.docker.compose.service=web,"
                    "com.docker.compose.project.config_files=/srv/site/compose.yaml"
                ),
            }
        ]

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    def _inspect_payload(self) -> dict[str, object]:
        if self.converged:
            return {
                "Id": "abc123def0",
                "Image": self.image_digest,
                "Config": {
                    "Image": "nginx:1.27",
                    "Cmd": None,
                    "Entrypoint": None,
                    "Env": None,
                    "Labels": {
                        "com.docker.compose.project": "site",
                        "com.docker.compose.service": "web",
                        "com.docker.compose.project.config_files": "/srv/site/compose.yaml",
                    },
                },
                "HostConfig": {
                    "RestartPolicy": {"Name": "", "MaximumRetryCount": 0},
                    "PortBindings": {},
                },
                "State": {"Status": "running", "Running": True},
                "NetworkSettings": {"Ports": {}, "Networks": {"site_default": {}}},
                "Mounts": [],
            }
        return {
            "Id": "abc123def0",
            "Image": "sha256:" + "1" * 64,
            "Config": {
                "Image": "nginx:1.26",
                "Cmd": ["nginx"],
                "Entrypoint": None,
                "Env": ["LOG_LEVEL=debug"],
                "Labels": {
                    "com.docker.compose.project": "site",
                    "com.docker.compose.service": "web",
                    "com.docker.compose.project.config_files": "/srv/site/compose.yaml",
                },
            },
            "HostConfig": {
                "RestartPolicy": {"Name": "always", "MaximumRetryCount": 0},
                "PortBindings": {},
            },
            "State": {"Status": "running", "Running": True},
            "NetworkSettings": {"Ports": {}, "Networks": {"site_default": {}}},
            "Mounts": [],
        }

    async def docker_ps_filter(
        self, *, service: str, project: str | None = None
    ) -> dict[str, object]:
        from mikrus_mcp.docker_ops import ps_labels

        matches = [
            item
            for item in self.ps_entries
            if ps_labels(item).get("com.docker.compose.service") == service
            and (project is None or ps_labels(item).get("com.docker.compose.project") == project)
        ]
        return {"containers": matches}

    async def docker_inspect(self, ids: list[str]) -> dict[str, object]:
        return {"containers": [self._inspect_payload() for _ in ids], "stderr_tail": ""}

    async def docker_compose_config(self, *, project: str, files: list[str]) -> dict[str, object]:
        return {"config": self.compose_cfg}

    async def docker_image_inspect(self, image: str) -> dict[str, object]:
        return {"image": {"Id": self.image_digest, "RepoDigests": []}}

    async def docker_compose_up(
        self, *, project: str, files: list[str], service: str
    ) -> dict[str, object]:
        self.ups.append({"project": project, "files": list(files), "service": service})
        return {"status": "APPLIED"}

    async def docker_service_wait(
        self, *, container_id: str, readiness: str, timeout_seconds: float
    ) -> dict[str, object]:
        self.waits.append({"readiness": readiness, "timeout_seconds": timeout_seconds})
        return {"status": "READY", "state": "running", "health": None}


def _docker_settings(client: FakeDockerComposeClient, *, store: Any = None) -> Settings:
    values: dict[str, Any] = {
        "targets": {"host": _ssh_target()},
        "default_target": "host",
        "allowed_scopes": frozenset(
            {"tool:*", "target:*", "target-id:*", "resource:*", "data:*", "write:server"}
        ),
        "write_enabled": True,
    }
    if store is not None:
        values["docker_plan_store_file"] = store
    return Settings(**values)


@pytest.mark.asyncio
async def test_docker_capabilities_are_ssh_only_and_unavailable_on_mikrus(tmp_path: Path) -> None:
    from mikrus_mcp.manifests import active_names, inactive_reason

    client = FakeDockerComposeClient(_ssh_target())
    settings = _docker_settings(client, store=tmp_path / "plans.json")
    for name in (
        "docker_runtime_snapshot",
        "docker_recreate_plan",
        "docker_recreate_apply",
        "service_wait",
    ):
        assert name in active_names(settings)

    no_store = _docker_settings(client)
    assert "docker_recreate_plan" not in active_names(no_store)
    assert "docker_recreate_apply" not in active_names(no_store)
    assert "service_wait" not in active_names(no_store)
    assert "docker_runtime_snapshot" in active_names(no_store)
    assert inactive_reason("docker_recreate_apply", no_store) == {
        "code": "STORE_NOT_CONFIGURED",
        "message": "requires MCP_DOCKER_PLAN_STORE_FILE",
    }

    only_mikrus = Settings(
        targets={"prod": _mikrus_target()},
        default_target="prod",
        allowed_scopes=frozenset({"tool:*", "target:*", "target-id:*", "resource:*", "data:*"}),
    )
    assert "docker_runtime_snapshot" not in active_names(only_mikrus)
    assert inactive_reason("docker_recreate_apply", only_mikrus) == {
        "code": "SSH_TARGET_REQUIRED",
        "message": "requires at least one configured SSH target",
    }

    client = FakeDockerComposeClient(_ssh_target())
    registry = TargetRegistry(
        {"prod": _mikrus_target(), "host": _ssh_target()},
        factory=lambda _: client,  # type: ignore[arg-type]
    )
    settings = Settings(
        targets={"prod": _mikrus_target(), "host": _ssh_target()},
        default_target="host",
        allowed_scopes=frozenset(
            {"tool:*", "target:*", "target-id:*", "resource:*", "data:*", "write:server"}
        ),
        write_enabled=True,
    )
    kernel = InvocationKernel(settings, registry=registry)
    result = await kernel.invoke(
        "docker_runtime_snapshot",
        {"server": "prod", "service": "web"},
        CallerContext("principal", settings.allowed_scopes),
    )
    assert result["error"]["code"] == "UNAVAILABLE"
    assert not client.ups


@pytest.mark.asyncio
async def test_docker_snapshot_requires_exactly_one_selector() -> None:
    client = FakeDockerComposeClient(_ssh_target())
    settings = _docker_settings(client)
    kernel = InvocationKernel(
        settings,
        registry=TargetRegistry(
            dict(settings.targets),
            factory=lambda _: client,  # type: ignore[arg-type]
        ),
    )
    caller = CallerContext("principal", settings.allowed_scopes)
    both = await kernel.invoke(
        "docker_runtime_snapshot",
        {"service": "web", "container": "abc123"},
        caller,
    )
    assert both["error"]["code"] == "VALIDATION_FAILED"
    neither = await kernel.invoke("docker_runtime_snapshot", {}, caller)
    assert neither["error"]["code"] == "VALIDATION_FAILED"
    snapshot = await kernel.invoke("docker_runtime_snapshot", {"service": "web"}, caller)
    assert snapshot["success"] is True
    assert snapshot["data"]["containers"][0]["service"] == "web"


@pytest.mark.asyncio
async def test_docker_plan_hides_env_values_and_apply_is_record_bound(tmp_path: Path) -> None:
    client = FakeDockerComposeClient(_ssh_target())
    settings = _docker_settings(client, store=tmp_path / "plans.json")
    approvals = ApprovalRegistry()
    kernel = InvocationKernel(
        settings,
        registry=TargetRegistry(
            dict(settings.targets),
            factory=lambda _: client,  # type: ignore[arg-type]
        ),
        approvals=approvals,
    )
    caller = CallerContext("principal", settings.allowed_scopes)

    plan = await kernel.invoke("docker_recreate_plan", {"service": "web"}, caller)
    assert plan["success"] is True
    plan_data = plan["data"]
    assert plan_data["plan_receipt"].startswith("plan:v1:sha256:")
    assert plan_data["project"] == "site"
    assert plan_data["image_digest"] == client.image_digest
    assert "image" in plan_data["runtime_only_drift"]

    receipt = str(plan_data["plan_receipt"])
    arguments = {"service": "web", "plan_receipt": receipt}
    approvals.issue_for_test(
        "docker_recreate_apply",
        "principal",
        client.stable_identity,
        "web",
        normalized_arguments_digest(arguments),
    )
    refused = await kernel.invoke("docker_recreate_apply", arguments, caller)
    assert refused["error"]["code"] == "RECREATE_CONFIG_DRIFT"
    assert "allow_runtime_drift" in refused["error"]["message"]
    assert not client.ups

    unapproved = await kernel.invoke("docker_recreate_apply", arguments, caller)
    assert unapproved["error"]["code"] == "AUTHORIZATION_FAILED"

    accepted_plan = await kernel.invoke(
        "docker_recreate_plan",
        {"service": "web", "allow_runtime_drift": True},
        caller,
    )
    assert accepted_plan["data"]["allow_runtime_drift"] is True
    receipt = str(accepted_plan["data"]["plan_receipt"])
    arguments = {"service": "web", "plan_receipt": receipt}
    denied = await kernel.invoke("docker_recreate_apply", arguments, caller)
    assert denied["error"]["code"] == "AUTHORIZATION_FAILED"

    approvals.issue_for_test(
        "docker_recreate_apply",
        "principal",
        client.stable_identity,
        "web",
        normalized_arguments_digest(arguments),
    )
    applied = await kernel.invoke("docker_recreate_apply", arguments, caller)
    assert applied["success"] is True
    assert applied["data"]["status"] == "APPLIED"
    assert applied["data"]["post_wait"] == {
        "status": "READY",
        "readiness": "running",
        "state": "running",
        "health": None,
    }
    assert client.ups == [
        {"project": "site", "files": ["/srv/site/compose.yaml"], "service": "web"}
    ]

    client.converged = True
    clean_plan = await kernel.invoke("docker_recreate_plan", {"service": "web"}, caller)
    assert clean_plan["data"]["has_runtime_only_drift"] is False
    receipt = str(clean_plan["data"]["plan_receipt"])
    arguments = {"service": "web", "plan_receipt": receipt}
    approvals.issue_for_test(
        "docker_recreate_apply",
        "principal",
        client.stable_identity,
        "web",
        normalized_arguments_digest(arguments),
    )
    already = await kernel.invoke("docker_recreate_apply", arguments, caller)
    assert already["success"] is True
    assert already["data"]["status"] == "ALREADY_APPLIED"
    assert already["data"]["post_wait"] is None
    assert len(client.ups) == 1

    unknown = {"service": "web", "plan_receipt": "plan:v1:sha256:" + "0" * 64}
    approvals.issue_for_test(
        "docker_recreate_apply",
        "principal",
        client.stable_identity,
        "web",
        normalized_arguments_digest(unknown),
    )
    stale = await kernel.invoke("docker_recreate_apply", unknown, caller)
    assert stale["error"]["code"] == "CONFLICT"
    assert "PLAN_STALE" in stale["error"]["message"]

    wrong_service = {"service": "api", "plan_receipt": receipt}
    approvals.issue_for_test(
        "docker_recreate_apply",
        "principal",
        client.stable_identity,
        "api",
        normalized_arguments_digest(wrong_service),
    )
    mismatch = await kernel.invoke("docker_recreate_apply", wrong_service, caller)
    assert mismatch["error"]["code"] == "VALIDATION_FAILED"

    client.image_digest = "sha256:" + "8" * 64
    approvals.issue_for_test(
        "docker_recreate_apply",
        "principal",
        client.stable_identity,
        "web",
        normalized_arguments_digest(arguments),
    )
    drifted = await kernel.invoke("docker_recreate_apply", arguments, caller)
    assert drifted["error"]["code"] == "CONFLICT"
    assert "IMAGE_DRIFT" in drifted["error"]["message"]


@pytest.mark.asyncio
async def test_docker_apply_classification_derives_from_record(tmp_path: Path) -> None:
    client = FakeDockerComposeClient(_ssh_target())
    settings = _docker_settings(client, store=tmp_path / "plans.json")
    approvals = ApprovalRegistry()
    kernel = InvocationKernel(
        settings,
        registry=TargetRegistry(
            dict(settings.targets),
            factory=lambda _: client,  # type: ignore[arg-type]
        ),
        approvals=approvals,
    )
    caller = CallerContext("principal", settings.allowed_scopes)

    client.converged = True
    plan = await kernel.invoke(
        "docker_recreate_plan",
        {"service": "web", "desired_image": "nginx:1.27"},
        caller,
    )
    assert plan["success"] is True
    from mikrus_mcp.docker_ops import PlanRecordStore

    store = PlanRecordStore(tmp_path / "plans.json")
    record = store.get(receipt_digest_value(str(plan["data"]["plan_receipt"])))
    assert record is not None
    assert record.desired_image_explicit is True
    assert record.desired_image == "nginx:1.27"
    assert record.service == "web"
    assert record.project == "site"

    client.image_digest = "sha256:" + "7" * 64
    arguments = {"service": "web", "plan_receipt": str(plan["data"]["plan_receipt"])}
    approvals.issue_for_test(
        "docker_recreate_apply",
        "principal",
        client.stable_identity,
        "web",
        normalized_arguments_digest(arguments),
    )
    stale = await kernel.invoke("docker_recreate_apply", arguments, caller)
    assert stale["error"]["code"] == "CONFLICT"
    assert "PLAN_STALE" in stale["error"]["message"]
    assert not client.ups


@pytest.mark.asyncio
async def test_docker_apply_detects_compose_config_change_after_plan(tmp_path: Path) -> None:
    client = FakeDockerComposeClient(_ssh_target())
    settings = _docker_settings(client, store=tmp_path / "plans.json")
    approvals = ApprovalRegistry()
    kernel = InvocationKernel(
        settings,
        registry=TargetRegistry(
            dict(settings.targets),
            factory=lambda _: client,  # type: ignore[arg-type]
        ),
        approvals=approvals,
    )
    caller = CallerContext("principal", settings.allowed_scopes)
    client.converged = True
    plan = await kernel.invoke("docker_recreate_plan", {"service": "web"}, caller)
    assert plan["success"] is True

    client.compose_cfg = {"services": {"web": {"image": "nginx:1.28"}}}
    arguments = {"service": "web", "plan_receipt": str(plan["data"]["plan_receipt"])}
    approvals.issue_for_test(
        "docker_recreate_apply",
        "principal",
        client.stable_identity,
        "web",
        normalized_arguments_digest(arguments),
    )
    result = await kernel.invoke("docker_recreate_apply", arguments, caller)
    assert result["error"]["code"] == "CONFLICT"
    assert "PLAN_STALE" in result["error"]["message"]
    assert not client.ups


def receipt_digest_value(receipt: str) -> str:
    return receipt.split(":")[-1]


@pytest.mark.asyncio
async def test_docker_ambiguous_service_and_wait(tmp_path: Path) -> None:
    client = FakeDockerComposeClient(_ssh_target())
    client.ps_entries.append(
        {
            "ID": "fff000",
            "Names": ["/other-web-1"],
            "Labels": (
                "com.docker.compose.project=other,"
                "com.docker.compose.service=web,"
                "com.docker.compose.project.config_files=/srv/other/compose.yaml"
            ),
        }
    )
    settings = _docker_settings(client, store=tmp_path / "plans.json")
    kernel = InvocationKernel(
        settings,
        registry=TargetRegistry(
            dict(settings.targets),
            factory=lambda _: client,  # type: ignore[arg-type]
        ),
    )
    caller = CallerContext("principal", settings.allowed_scopes)
    ambiguous = await kernel.invoke("docker_recreate_plan", {"service": "web"}, caller)
    assert ambiguous["error"]["code"] == "CONFLICT"
    assert "AMBIGUOUS_SERVICE" in ambiguous["error"]["message"]

    client.ps_entries = client.ps_entries[:1]
    client.converged = True
    plan = await kernel.invoke("docker_recreate_plan", {"service": "web"}, caller)
    receipt = str(plan["data"]["plan_receipt"])
    waited = await kernel.invoke(
        "service_wait",
        {"service": "web", "plan_receipt": receipt, "timeout_seconds": 5},
        caller,
    )
    assert waited["success"] is True
    assert waited["data"]["status"] == "READY"
    assert client.waits[-1]["timeout_seconds"] == 5.0

    client.image_digest = "sha256:" + "6" * 64
    waited_again = await kernel.invoke(
        "service_wait",
        {"service": "web", "plan_receipt": receipt, "timeout_seconds": 5},
        caller,
    )
    assert waited_again["success"] is True


@pytest.mark.asyncio
async def test_docker_apply_runs_inline_readiness_wait(tmp_path: Path) -> None:
    client = FakeDockerComposeClient(_ssh_target())
    settings = _docker_settings(client, store=tmp_path / "plans.json")
    approvals = ApprovalRegistry()
    kernel = InvocationKernel(
        settings,
        registry=TargetRegistry(
            dict(settings.targets),
            factory=lambda _: client,  # type: ignore[arg-type]
        ),
        approvals=approvals,
    )
    caller = CallerContext("principal", settings.allowed_scopes)
    plan = await kernel.invoke(
        "docker_recreate_plan",
        {"service": "web", "allow_runtime_drift": True},
        caller,
    )
    receipt = str(plan["data"]["plan_receipt"])
    arguments = {
        "service": "web",
        "plan_receipt": receipt,
        "readiness": "running",
        "timeout_seconds": 8.5,
    }
    approvals.issue_for_test(
        "docker_recreate_apply",
        "principal",
        client.stable_identity,
        "web",
        normalized_arguments_digest(arguments),
    )
    applied = await kernel.invoke("docker_recreate_apply", arguments, caller)
    assert applied["success"] is True
    assert applied["data"]["status"] == "APPLIED"
    assert applied["data"]["post_wait"] == {
        "status": "READY",
        "readiness": "running",
        "state": "running",
        "health": None,
    }
    assert client.waits[-1] == {"readiness": "running", "timeout_seconds": 8.5}


class AmbiguousStartClient(FakeDockerComposeClient):
    """Client whose remote job start times out ambiguously after launch."""

    def __init__(self, config: TargetConfig) -> None:
        super().__init__(config)
        self.launched: list[str] = []

    async def remote_job_start(self, **kwargs: object) -> dict[str, object]:
        job_id = str(kwargs.get("job_id"))
        self.launched.append(job_id)
        raise AppError(ErrorCode.AMBIGUOUS, "SSH program outcome is unknown after timeout")

    async def remote_job_status(self, *, job_id: str) -> dict[str, object]:
        if job_id in self.launched:
            return {"jobId": job_id, "state": "running", "exitCode": None}
        raise AppError(ErrorCode.NOT_FOUND, "remote job not found")


@pytest.mark.asyncio
async def test_remote_job_start_reconciles_after_ambiguity(tmp_path: Path) -> None:
    client = AmbiguousStartClient(_ssh_target())
    settings = Settings(
        targets={"host": _ssh_target()},
        default_target="host",
        allowed_scopes=frozenset(
            {"tool:*", "target:*", "target-id:*", "resource:*", "data:*", "write:server"}
        ),
        write_enabled=True,
        remote_job_store_file=tmp_path / "jobs.json",
    )
    approvals = ApprovalRegistry()
    kernel = InvocationKernel(
        settings,
        registry=TargetRegistry(
            dict(settings.targets),
            factory=lambda _: client,  # type: ignore[arg-type]
        ),
        approvals=approvals,
    )
    caller = CallerContext("principal", settings.allowed_scopes)
    arguments = {
        "idempotency_key": "reconcile-me",
        "executable": "tail",
        "argv": ["-f", "/tmp/x"],
    }
    approvals.issue_for_test(
        "remote_job_start",
        "principal",
        client.stable_identity,
        "reconcile-me",
        normalized_arguments_digest(arguments),
    )
    result = await kernel.invoke("remote_job_start", arguments, caller)
    assert result["success"] is True
    assert result["data"]["reused"] is True
    assert result["data"]["reconciled_after_ambiguity"] is True
    assert result["data"]["state"] == "running"
    assert len(client.launched) == 1


@pytest.mark.asyncio
async def test_remote_job_cancel_reports_termination_field(tmp_path: Path) -> None:
    class CancelledJobClient(FakeDockerComposeClient):
        async def remote_job_cancel(self, *, job_id: str, reason: str) -> dict[str, object]:
            del reason
            return {"jobId": job_id, "state": "cancelled", "terminated": False}

    from mikrus_mcp.remote_jobs import RemoteJobRecord, RemoteJobStore

    client = CancelledJobClient(_ssh_target())
    settings = Settings(
        targets={"host": _ssh_target()},
        default_target="host",
        allowed_scopes=frozenset(
            {"tool:*", "target:*", "target-id:*", "resource:*", "data:*", "write:server"}
        ),
        write_enabled=True,
        remote_job_store_file=tmp_path / "jobs.json",
    )
    store = RemoteJobStore(tmp_path / "jobs.json")
    record = RemoteJobRecord.create(
        principal="principal",
        server_id="host",
        target_identity=client.stable_identity,
        idempotency_key="cancel-me",
        request_digest_value="a" * 64,
        now="2026-09-10T12:00:00Z",
    )
    record.transition("running", now="2026-09-10T12:00:01Z")
    store.save(record)
    approvals = ApprovalRegistry()
    kernel = InvocationKernel(
        settings,
        registry=TargetRegistry(
            dict(settings.targets),
            factory=lambda _: client,  # type: ignore[arg-type]
        ),
        approvals=approvals,
    )
    caller = CallerContext("principal", settings.allowed_scopes)
    arguments = {"job_id": record.job_id, "reason": "operator request"}
    approvals.issue_for_test(
        "remote_job_cancel",
        "principal",
        client.stable_identity,
        record.job_id,
        normalized_arguments_digest(arguments),
    )
    result = await kernel.invoke("remote_job_cancel", arguments, caller)
    assert result["success"] is True
    assert "terminated" in result["data"]
    assert result["data"]["terminated"] is False
    assert result["data"]["state"] == "cancelled"


class UnreconcilableStartClient(AmbiguousStartClient):
    """Client whose reconciliation lookup also fails."""

    async def remote_job_status(self, *, job_id: str) -> dict[str, object]:
        raise AppError(ErrorCode.UPSTREAM, "connection lost during lookup")


@pytest.mark.asyncio
async def test_remote_job_start_surfaces_ambiguity_when_lookup_fails(
    tmp_path: Path,
) -> None:
    client = UnreconcilableStartClient(_ssh_target())
    settings = Settings(
        targets={"host": _ssh_target()},
        default_target="host",
        allowed_scopes=frozenset(
            {"tool:*", "target:*", "target-id:*", "resource:*", "data:*", "write:server"}
        ),
        write_enabled=True,
        remote_job_store_file=tmp_path / "jobs.json",
    )
    approvals = ApprovalRegistry()
    kernel = InvocationKernel(
        settings,
        registry=TargetRegistry(
            dict(settings.targets),
            factory=lambda _: client,  # type: ignore[arg-type]
        ),
        approvals=approvals,
    )
    caller = CallerContext("principal", settings.allowed_scopes)
    arguments = {
        "idempotency_key": "unreconcilable",
        "executable": "tail",
        "argv": ["-f", "/tmp/x"],
    }
    approvals.issue_for_test(
        "remote_job_start",
        "principal",
        client.stable_identity,
        "unreconcilable",
        normalized_arguments_digest(arguments),
    )
    result = await kernel.invoke("remote_job_start", arguments, caller)
    assert result["error"]["code"] == "AMBIGUOUS_OUTCOME"
    assert "could not be reconciled" in result["error"]["message"]


@pytest.mark.asyncio
async def test_docker_apply_rejects_invalid_tuning_before_side_effects(
    tmp_path: Path,
) -> None:
    client = FakeDockerComposeClient(_ssh_target())
    settings = _docker_settings(client, store=tmp_path / "plans.json")
    approvals = ApprovalRegistry()
    kernel = InvocationKernel(
        settings,
        registry=TargetRegistry(
            dict(settings.targets),
            factory=lambda _: client,  # type: ignore[arg-type]
        ),
        approvals=approvals,
    )
    caller = CallerContext("principal", settings.allowed_scopes)
    client.converged = True
    plan = await kernel.invoke("docker_recreate_plan", {"service": "web"}, caller)
    receipt = str(plan["data"]["plan_receipt"])

    for arguments in (
        {
            "service": "web",
            "plan_receipt": receipt,
            "timeout_seconds": 900,
        },
        {
            "service": "web",
            "plan_receipt": receipt,
            "readiness": "bogus",
        },
    ):
        approvals.issue_for_test(
            "docker_recreate_apply",
            "principal",
            client.stable_identity,
            "web",
            normalized_arguments_digest(arguments),
        )
        result = await kernel.invoke("docker_recreate_apply", arguments, caller)
        assert result["error"]["code"] == "VALIDATION_FAILED"
        assert not client.ups
        assert not client.waits


class FlakyCronClient(FakeSshJobsClient):
    """Cron client whose install can fail after (or without) persisting."""

    install_error: AppError | None = None
    persist_despite_error: bool = False

    async def cron_install(self, *, expected_hash: str, new_text: str) -> dict[str, object]:
        import hashlib

        if self.persist_despite_error:
            self.installs.append(new_text)
            self.crontab = new_text
        if self.install_error is not None:
            raise self.install_error
        if hashlib.sha256(self.crontab.encode("utf-8")).hexdigest() != expected_hash:
            raise AppError(
                ErrorCode.CONFLICT,
                "the installed crontab changed concurrently (CONCURRENT_MODIFICATION)",
            )
        self.installs.append(new_text)
        self.crontab = new_text
        return {"status": "INSTALLED", "hash": expected_hash, "size": len(new_text)}


def _cron_arguments(profile_id: str = "backup") -> dict[str, Any]:
    return {
        "profile_id": profile_id,
        "schedule": _schedule(),
        "executable": "grep",
        "argv": [],
        "environment": {},
    }


@pytest.mark.asyncio
async def test_cron_upsert_failure_rolls_back_only_its_own_record(tmp_path: Path) -> None:
    from mikrus_mcp.cron_profiles import CronProfileStore

    client = FlakyCronClient(_ssh_target())
    client.install_error = AppError(ErrorCode.UPSTREAM, "crontab write failed")
    store_file = tmp_path / "cron.json"
    settings = _cron_settings(client, store_file=store_file, write_enabled=True)
    approvals = ApprovalRegistry()
    kernel = InvocationKernel(
        settings,
        registry=TargetRegistry(
            dict(settings.targets),
            factory=lambda _: client,  # type: ignore[arg-type]
        ),
        approvals=approvals,
    )
    caller = CallerContext("principal", settings.allowed_scopes)
    arguments = _cron_arguments()
    approvals.issue_for_test(
        "cron_upsert",
        "principal",
        client.stable_identity,
        "backup",
        normalized_arguments_digest(arguments),
    )
    result = await kernel.invoke("cron_upsert", arguments, caller)
    assert result["error"]["code"] == "UPSTREAM_FAILED"
    store = CronProfileStore(store_file)
    with pytest.raises(AppError):
        store.get(profile_id="backup", principal="principal", server_id="host")

    client.install_error = None
    approvals.issue_for_test(
        "cron_upsert",
        "principal",
        client.stable_identity,
        "backup",
        normalized_arguments_digest(arguments),
    )
    first = await kernel.invoke("cron_upsert", arguments, caller)
    assert first["success"] is True
    persisted = store.get(profile_id="backup", principal="principal", server_id="host")

    client.install_error = AppError(ErrorCode.UPSTREAM, "crontab write failed")
    updated = dict(arguments, argv=["--changed"])
    approvals.issue_for_test(
        "cron_upsert",
        "principal",
        client.stable_identity,
        "backup",
        normalized_arguments_digest(updated),
    )
    second = await kernel.invoke("cron_upsert", updated, caller)
    assert second["error"]["code"] == "UPSTREAM_FAILED"
    restored = store.get(profile_id="backup", principal="principal", server_id="host")
    assert restored.updated_at == persisted.updated_at
    assert restored.argv == persisted.argv


@pytest.mark.asyncio
async def test_cron_upsert_ambiguous_reconciles_against_installed_projection(
    tmp_path: Path,
) -> None:
    from mikrus_mcp.cron_profiles import (
        CronProfileStore,
        desired_digest,
        generate_cron_line,
        marker_line,
    )

    client = FlakyCronClient(_ssh_target())
    client.install_error = AppError(ErrorCode.AMBIGUOUS, "outcome unknown after timeout")
    client.persist_despite_error = True
    settings = _cron_settings(client, store_file=tmp_path / "cron.json", write_enabled=True)
    approvals = ApprovalRegistry()
    kernel = InvocationKernel(
        settings,
        registry=TargetRegistry(
            dict(settings.targets),
            factory=lambda _: client,  # type: ignore[arg-type]
        ),
        approvals=approvals,
    )
    caller = CallerContext("principal", settings.allowed_scopes)
    arguments = _cron_arguments()
    approvals.issue_for_test(
        "cron_upsert",
        "principal",
        client.stable_identity,
        "backup",
        normalized_arguments_digest(arguments),
    )
    result = await kernel.invoke("cron_upsert", arguments, caller)
    assert result["success"] is True
    assert result["data"]["reconciled_after_ambiguity"] is True
    assert "mikrus-mcp:backup" in client.crontab
    store = CronProfileStore(tmp_path / "cron.json")
    assert store.get(profile_id="backup", principal="principal", server_id="host")

    client.persist_despite_error = False
    rolled_back_line = generate_cron_line(
        schedule=_schedule(), executable="grep", argv=[], environment={}
    )
    rolled_back_digest = desired_digest(rolled_back_line)
    client.install_error = AppError(ErrorCode.AMBIGUOUS, "outcome unknown after timeout")
    ambiguous_arguments = _cron_arguments("second")
    approvals.issue_for_test(
        "cron_upsert",
        "principal",
        client.stable_identity,
        "second",
        normalized_arguments_digest(ambiguous_arguments),
    )
    rolled_back = await kernel.invoke("cron_upsert", ambiguous_arguments, caller)
    assert rolled_back["error"]["code"] == "AMBIGUOUS_OUTCOME"
    with pytest.raises(AppError):
        store.get(profile_id="second", principal="principal", server_id="host")
    assert marker_line("second", rolled_back_digest) not in client.crontab


@pytest.mark.asyncio
async def test_docker_apply_requires_acceptance_for_drift_appearing_after_plan(
    tmp_path: Path,
) -> None:
    client = FakeDockerComposeClient(_ssh_target())
    settings = _docker_settings(client, store=tmp_path / "plans.json")
    approvals = ApprovalRegistry()
    kernel = InvocationKernel(
        settings,
        registry=TargetRegistry(
            dict(settings.targets),
            factory=lambda _: client,  # type: ignore[arg-type]
        ),
        approvals=approvals,
    )
    caller = CallerContext("principal", settings.allowed_scopes)
    client.converged = True
    plan = await kernel.invoke("docker_recreate_plan", {"service": "web"}, caller)
    assert plan["data"]["has_runtime_only_drift"] is False

    client.converged = False
    arguments = {"service": "web", "plan_receipt": str(plan["data"]["plan_receipt"])}
    approvals.issue_for_test(
        "docker_recreate_apply",
        "principal",
        client.stable_identity,
        "web",
        normalized_arguments_digest(arguments),
    )
    refused = await kernel.invoke("docker_recreate_apply", arguments, caller)
    assert refused["error"]["code"] == "RECREATE_CONFIG_DRIFT"
    assert client.ups == []
