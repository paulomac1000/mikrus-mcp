"""Kernel-path semantic acceptance for the file_patch_atomic CAS conflict.

The unit contract previously covered the typed success path and pre-I/O
digest-format validation; the digest-mismatch conflict raised by the SSH
adapter was only exercised against the real system. This pins the kernel-path
behavior: a CAS precondition failure surfaces as a non-retried CONFLICT result.
"""

from __future__ import annotations

import pytest

from mikrus_mcp.approvals import normalized_arguments_digest
from mikrus_mcp.config import Settings, TargetConfig
from mikrus_mcp.errors import AppError, ErrorCode
from mikrus_mcp.kernel import ApprovalRegistry, CallerContext, InvocationKernel, TargetRegistry


def _ssh_target() -> TargetConfig:
    return TargetConfig("host", "ssh", host="server.example")


class CasConflictClient:
    """Kernel-level double mirroring the SSH adapter's CAS-conflict failure."""

    def __init__(self, config: TargetConfig) -> None:
        self.config = config
        self.stable_identity = f"{config.stable_identity}#host-key=SHA256:test-host-key"
        self.patch_attempts = 0

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def file_patch_atomic(
        self, *, path: str, expected_digest: str, content_b64: str
    ) -> dict[str, object]:
        self.patch_attempts += 1
        raise AppError(
            ErrorCode.CONFLICT,
            "file patch CAS precondition failed; current file digest differs (CONFLICT)",
        )


@pytest.mark.asyncio
async def test_file_patch_digest_mismatch_surfaces_conflict_without_retry() -> None:
    client = CasConflictClient(_ssh_target())
    settings = Settings(
        {"host": _ssh_target()},
        "host",
        allowed_scopes=frozenset(
            {"tool:*", "target:*", "target-id:*", "resource:*", "data:*", "write:server"}
        ),
        write_enabled=True,
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
        "path": "/tmp/srv/config.txt",
        "expected_digest": "sha256:" + "a" * 64,
        "content_b64": "SGVsbG8=",
    }
    approvals.issue_for_test(
        "file_patch_atomic",
        "principal",
        client.stable_identity,
        "/tmp/srv/config.txt",
        normalized_arguments_digest(arguments),
    )

    result = await kernel.invoke("file_patch_atomic", arguments, caller)

    assert result["success"] is False
    assert result["error"]["code"] == "CONFLICT"
    assert "CAS precondition failed" in result["error"]["message"]
    # A failed CAS precondition is never automatically retried.
    assert client.patch_attempts == 1
