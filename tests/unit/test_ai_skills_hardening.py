from __future__ import annotations

import json
import shutil
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from mikrus_mcp.approvals import ApprovalRegistry, normalized_arguments_digest
from mikrus_mcp.clients.common import _remote_atomic_write_command
from mikrus_mcp.client import SshClient
from mikrus_mcp.config import Settings, TargetConfig, load_settings
from mikrus_mcp.kernel import CallerContext, InvocationKernel
from mikrus_mcp.manifests import MANIFESTS, active_names
from mikrus_mcp.targets import TargetRegistry
from mikrus_mcp.tool_common import _require_success


class _HostKey:
    def get_fingerprint(self, algorithm: str = "sha256") -> str:
        assert algorithm == "sha256"
        return "SHA256:test-peer"


class _Connection:
    def __init__(self) -> None:
        self.closed = False

    def is_closed(self) -> bool:
        return self.closed

    def get_server_host_key(self) -> _HostKey:
        return _HostKey()

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


@pytest.mark.asyncio
async def test_ssh_identity_binds_verified_host_key(monkeypatch: pytest.MonkeyPatch) -> None:
    async def connect(**_: Any) -> _Connection:
        return _Connection()

    monkeypatch.setitem(
        sys.modules,
        "asyncssh",
        types.SimpleNamespace(connect=connect, read_known_hosts=lambda value: value),
    )
    config = TargetConfig("prod", "ssh", host="server.example", user="deploy", port=2222)
    client = SshClient(config)
    await client.open()
    assert client.stable_identity == (
        "ssh:deploy@server.example:2222#host-key=SHA256:test-peer"
    )
    await client.close()


def test_insecure_ssh_cannot_enable_writes() -> None:
    target = TargetConfig("ssh", "ssh", host="127.0.0.1", verify_host_key=False)
    with pytest.raises(ValueError, match="cannot be used for writes"):
        Settings(
            {"ssh": target},
            "ssh",
            allow_insecure_ssh=True,
            write_enabled=True,
        ).validate()


def test_active_catalog_separates_supported_from_runtime_active() -> None:
    ssh = TargetConfig("ssh", "ssh", host="127.0.0.1")
    settings = Settings({"ssh": ssh}, "ssh")
    active = active_names(settings)
    assert "get_memory_info" in active
    assert "get_server_info" not in active
    assert "write_file" not in active
    kernel = InvocationKernel(settings, registry=TargetRegistry({"ssh": ssh}))
    catalog = {entry["id"]: entry for entry in kernel.catalog(active_only=False)}
    assert catalog["get_server_info"]["active_state"] == "inactive"
    assert "inactive_reason" in catalog["get_server_info"]["extensions"]
    assert catalog["get_memory_info"]["active_state"] == "active"


def test_capability_projection_uses_canonical_contract_fields() -> None:
    read = MANIFESTS["read_file"].as_dict()
    assert read["schema_version"] == 1
    assert read["operation_kind"] == "read"
    assert read["idempotent"] is True
    assert read["reversible"] is False
    assert read["idempotency_key_required"] is False
    assert read["protocol_revisions"] == ["2026-07-28", "2025-11-25"]
    write = MANIFESTS["write_file"].as_dict()
    assert write["operation_kind"] == "write"
    assert write["retryable"] is False
    assert write["approval"]["enforcement"] == "server-side"
    assert "arguments-digest" in write["approval"]["binds"]


def _run_remote(command: str, *, check: bool) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/sh", "-c", command],
        check=check,
        capture_output=True,
        text=True,
    )


def test_atomic_remote_write_rejects_symlink_components(tmp_path: Path) -> None:
    base = Path("/tmp") / f"mikrus-mcp-test-{tmp_path.name}"
    base.mkdir(mode=0o700, exist_ok=False)
    try:
        target = base / "value.txt"
        target.write_text("old", encoding="utf-8")
        _run_remote(_remote_atomic_write_command(str(target), "new"), check=True)
        assert target.read_text(encoding="utf-8") == "new"

        outside = base / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        target.unlink()
        target.symlink_to(outside)
        rejected = _run_remote(
            _remote_atomic_write_command(str(target), "blocked"), check=False
        )
        assert rejected.returncode != 0
        assert outside.read_text(encoding="utf-8") == "outside"

        real = base / "real"
        real.mkdir()
        link = base / "link"
        link.symlink_to(real, target_is_directory=True)
        rejected = _run_remote(
            _remote_atomic_write_command(str(link / "escape.txt"), "blocked"),
            check=False,
        )
        assert rejected.returncode != 0
        assert not (real / "escape.txt").exists()
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_default_deadline_no_longer_truncates_long_capabilities() -> None:
    settings = load_settings({"MIKRUS_API_KEY": "k", "MIKRUS_SERVER_NAME": "srv"})
    assert settings.default_deadline_ms == 120_000
    assert settings.server_max_deadline_ms == 120_000
    assert MANIFESTS["update_system"].timeout_ms == 120_000


def test_public_success_and_error_preserve_metadata_and_retry_guidance() -> None:
    success = _require_success(
        {
            "success": True,
            "data": {"ok": True},
            "_meta": {"request_id": "abc", "source": "mikrus-mcp"},
        }
    )
    assert success["_meta"] == {"request_id": "abc", "source": "mikrus-mcp"}
    with pytest.raises(ToolError) as captured:
        _require_success(
            {
                "success": False,
                "error": {
                    "code": "RATE_LIMITED",
                    "message": "slow down",
                    "retryable": True,
                    "retry_after_seconds": 2.0,
                },
                "_meta": {"request_id": "req"},
            }
        )
    payload = json.loads(str(captured.value))
    assert payload["error"]["retryable"] is True
    assert payload["error"]["retry_after_seconds"] == 2.0
    assert payload["_meta"]["request_id"] == "req"


class _ResolvedMutationClient:
    def __init__(self, config: TargetConfig) -> None:
        self.stable_identity = config.stable_identity + "#host-key=SHA256:peer"

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def write_file(self, path: str, content: str) -> dict[str, object]:
        return {"path": path, "bytes": len(content)}


@pytest.mark.asyncio
async def test_approval_uses_resolved_ssh_identity_not_selector_identity() -> None:
    target = TargetConfig("prod", "ssh", host="host")
    settings = Settings(
        {"prod": target},
        "prod",
        write_enabled=True,
        allowed_scopes=frozenset({"tool:*", "target:*", "write:server"}),
    )
    arguments = {"path": "/tmp/a", "content": "x"}
    digest = normalized_arguments_digest(arguments)

    async def invoke(identity: str) -> dict[str, Any]:
        client = _ResolvedMutationClient(target)
        registry = TargetRegistry(
            {"prod": target}, factory=lambda _: client  # type: ignore[arg-type]
        )
        approvals = ApprovalRegistry()
        approvals.issue_for_test("write_file", "principal", identity, "/tmp/a", digest)
        kernel = InvocationKernel(settings, registry=registry, approvals=approvals)
        try:
            return await kernel.invoke(
                "write_file",
                arguments,
                CallerContext("principal", settings.allowed_scopes),
            )
        finally:
            await kernel.close()

    rejected = await invoke(target.stable_identity)
    assert rejected["error"]["code"] == "AUTHORIZATION_FAILED"
    accepted = await invoke(target.stable_identity + "#host-key=SHA256:peer")
    assert accepted["success"] is True
    assert accepted["_meta"]["target_identity"].endswith("SHA256:peer")


@pytest.mark.asyncio
async def test_response_limit_counts_application_envelope_metadata() -> None:
    from dataclasses import replace

    class ReadClient:
        stable_identity = "mikrus:srv"

        async def open(self) -> None:
            return None

        async def close(self) -> None:
            return None

        async def get_server_info(self) -> dict[str, str]:
            return {"value": "x"}

    target = TargetConfig(
        "srv", "mikrus", api_url="https://api.mikr.us", api_key="k", server_id="srv"
    )
    settings = Settings({"srv": target}, "srv")
    client = ReadClient()
    registry = TargetRegistry({"srv": target}, factory=lambda _: client)  # type: ignore[arg-type]
    original = MANIFESTS["get_server_info"]
    MANIFESTS["get_server_info"] = replace(original, max_response_bytes=64)
    try:
        kernel = InvocationKernel(settings, registry=registry)
        result = await kernel.invoke(
            "get_server_info",
            {},
            CallerContext("principal", frozenset({"tool:*", "target:*"})),
        )
        assert result["success"] is False
        assert result["error"]["code"] == "UPSTREAM_FAILED"
    finally:
        MANIFESTS["get_server_info"] = original
