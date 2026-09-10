"""Provider- or real-system-backed acceptance checks left for the deployment agent."""

import os
import uuid

import pytest


@pytest.mark.real_backend
@pytest.mark.skip(
    reason=("TODO(real-system): verify stable SSH host fingerprint enrollment and revalidation")
)
def test_real_ssh_identity_revalidation() -> None:
    pass


@pytest.mark.real_backend
@pytest.mark.skip(
    reason=(
        "TODO(real-system): exercise every mikr.us mutation once and reconcile ambiguous outcomes"
    )
)
def test_real_mikrus_mutation_reconciliation() -> None:
    pass


@pytest.mark.real_backend
@pytest.mark.skip(
    reason=(
        "TODO(real-system): verify symlink-swap and TOCTOU resistance on the "
        "actual remote filesystem"
    )
)
def test_remote_filesystem_symlink_race() -> None:
    pass


def _real_ssh_endpoint() -> dict[str, object] | None:
    import json
    import os

    raw = os.environ.get("MIKRUS_REAL_SSH_ENDPOINT")
    if not raw:
        return None
    endpoint = json.loads(raw)
    if not isinstance(endpoint, dict):
        raise ValueError("MIKRUS_REAL_SSH_ENDPOINT must be a JSON object")
    return endpoint


@pytest.mark.real_backend
@pytest.mark.skipif(
    _real_ssh_endpoint() is None or not os.environ.get("MCP_REMOTE_JOB_STORE_FILE"),
    reason=(
        "TODO(real-system): set MIKRUS_REAL_SSH_ENDPOINT (json: host, port, user, "
        "ssh_key, known_hosts_file) and MCP_REMOTE_JOB_STORE_FILE to run the "
        "durable-job disconnect reconciliation against the dedicated real target"
    ),
)
def test_durable_remote_job_real_disconnect_reconciliation() -> None:
    """LIVE check: durable job survives connection loss on a dedicated SSH target.

    Requires explicit operator-provided credentials via environment; never
    repurposes production infrastructure (repository operating contract).
    """
    import asyncio
    import json

    from mikrus_mcp.approvals import ApprovalRegistry, normalized_arguments_digest
    from mikrus_mcp.config import load_settings
    from mikrus_mcp.kernel import CallerContext, InvocationKernel

    endpoint = _real_ssh_endpoint()
    assert endpoint is not None
    store = os.environ["MCP_REMOTE_JOB_STORE_FILE"]

    servers = {
        "real": {
            "type": "ssh",
            "host": endpoint["host"],
            "port": int(endpoint.get("port", 22)),
            "user": endpoint.get("user", "root"),
            "ssh_key": endpoint["ssh_key"],
            "known_hosts_file": endpoint["known_hosts_file"],
        }
    }
    environment = {
        "MCP_SERVERS": json.dumps(servers),
        "MCP_DEFAULT_SERVER": "real",
        "MCP_WRITE_ENABLED": "true",
        "MCP_ALLOWED_SCOPES": "tool:*,target:*,target-id:*,resource:*,data:*,write:server",
        "MCP_REMOTE_JOB_STORE_FILE": store,
    }
    settings = load_settings(environment)
    approvals = ApprovalRegistry()
    kernel = InvocationKernel(settings, approvals=approvals)
    caller = CallerContext("posix-uid-real", settings.allowed_scopes)

    async def scenario() -> None:
        await kernel.registry.get("real")
        start_identity = kernel.registry.resolved_identity("real")
        # fresh key per run: a previous run leaves the key in a terminal state
        # and durable idempotent reuse correctly refuses terminal records
        idempotency_key = f"deferred-disconnect-{uuid.uuid4().hex[:12]}"
        start_arguments = {
            "idempotency_key": idempotency_key,
            "executable": "tail",
            "argv": ["-f", "/etc/hostname"],
        }
        approvals.issue_for_test(
            "remote_job_start",
            "posix-uid-real",
            start_identity,
            idempotency_key,
            normalized_arguments_digest(start_arguments),
        )
        started = await kernel.invoke("remote_job_start", start_arguments, caller)
        assert started["success"] is True, started.get("error")
        job_id = str(started["data"]["jobId"])

        await kernel.registry.close()  # abandon the first connection

        reopened = InvocationKernel(load_settings(environment), approvals=approvals)
        await reopened.registry.get("real")
        wait_arguments = {"job_id": job_id, "timeout_seconds": 5}
        running = await reopened.invoke("remote_job_wait", wait_arguments, caller)
        assert running["success"] is True, running.get("error")
        assert running["data"]["state"] in {"running", "succeeded"}

        output_arguments = {"job_id": job_id, "stream": "stdout", "offset": 0, "max_bytes": 1024}
        first = await reopened.invoke("remote_job_output", output_arguments, caller)
        assert first["success"] is True, first.get("error")
        next_offset = int(first["data"].get("next_offset", 0))
        output_arguments["offset"] = next_offset
        second = await reopened.invoke("remote_job_output", output_arguments, caller)
        assert second["success"] is True, second.get("error")

        cancel_arguments = {"job_id": job_id, "reason": "deferred acceptance check"}
        approvals.issue_for_test(
            "remote_job_cancel",
            "posix-uid-real",
            reopened.registry.resolved_identity("real"),
            job_id,
            normalized_arguments_digest(cancel_arguments),
        )
        cancelled = await reopened.invoke("remote_job_cancel", cancel_arguments, caller)
        assert cancelled["success"] is True, cancelled.get("error")
        assert cancelled["data"]["state"] == "cancelled"
        assert cancelled["data"]["terminated"] is True
        await reopened.close()

    asyncio.run(scenario())


@pytest.mark.artifact
@pytest.mark.skip(
    reason=(
        "TODO(provider): local receipt verification was performed 2026-09-10 "
        "(binding=verified in-container plus host-versus-wheel); the remaining gap "
        "is registry promotion evidence for the deployed image digest"
    )
)
def test_deployed_release_receipt() -> None:
    pass


@pytest.mark.artifact
@pytest.mark.skip(
    reason=("TODO(provider): install and test exact wheels on macOS arm64 and Windows x64")
)
def test_cross_platform_exact_artifact_matrix() -> None:
    pass


@pytest.mark.artifact
@pytest.mark.skip(
    reason=("TODO(provider): smoke the pushed multi-architecture OCI digest on amd64 and arm64")
)
def test_published_multiarch_image_digest() -> None:
    pass


@pytest.mark.artifact
@pytest.mark.skip(
    reason=(
        "TODO(provider): resolve and verify complete platform-specific "
        "transitive dependency locks with hashes"
    )
)
def test_hashed_transitive_dependency_locks() -> None:
    pass
