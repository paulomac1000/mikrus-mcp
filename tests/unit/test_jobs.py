from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mikrus_mcp.errors import AppError, ErrorCode
from mikrus_mcp.jobs import ProgramJobRegistry
from mikrus_mcp.remote_jobs import (
    MAX_REMOTE_OUTPUT_BYTES,
    DurableRemoteJobRegistry,
    RemoteJobRecord,
    RemoteJobStore,
    request_digest,
)


def test_remote_job_record_is_bounded_and_serializable() -> None:
    digest = request_digest({"argv": ["build"], "executable": "make"})
    record = RemoteJobRecord.create(
        principal="principal",
        server_id="host",
        target_identity="ssh:host:fingerprint",
        idempotency_key="build-2026-09-10",
        request_digest_value=digest,
        now="2026-09-10T12:00:00Z",
    )

    record.append_output(stream="stdout", chunk="x" * (MAX_REMOTE_OUTPUT_BYTES + 10))
    record.transition("running", now="2026-09-10T12:00:01Z")
    record.transition("succeeded", now="2026-09-10T12:00:02Z")
    payload = record.as_dict()

    assert payload["state"] == "succeeded"
    assert payload["stdoutTruncated"] is True
    assert len(str(payload["stdout"]).encode("utf-8")) <= MAX_REMOTE_OUTPUT_BYTES
    assert payload["requestDigest"] == digest


def test_remote_job_record_rejects_transition_after_terminal_state() -> None:
    record = RemoteJobRecord.create(
        principal="principal",
        server_id="host",
        target_identity="ssh:host:fingerprint",
        idempotency_key="key",
        request_digest_value="a" * 64,
        now="2026-09-10T12:00:00Z",
    )
    record.transition("failed", now="2026-09-10T12:00:01Z")

    with pytest.raises(ValueError, match="terminal"):
        record.transition("running", now="2026-09-10T12:00:02Z")


def test_remote_job_store_round_trips_and_reuses_idempotent_record(tmp_path: Path) -> None:
    store = RemoteJobStore(tmp_path / "jobs.json")
    record = RemoteJobRecord.create(
        principal="principal",
        server_id="host",
        target_identity="ssh:host:fingerprint",
        idempotency_key="key",
        request_digest_value="a" * 64,
        now="2026-09-10T12:00:00Z",
    )

    store.save(record)

    loaded = store.find_idempotent(principal="principal", server_id="host", idempotency_key="key")
    assert loaded is not None
    assert loaded.job_id == record.job_id
    assert (tmp_path / "jobs.json").stat().st_mode & 0o077 == 0


def test_durable_registry_rejects_conflicting_retry_and_scopes_updates(tmp_path: Path) -> None:
    registry = DurableRemoteJobRegistry(RemoteJobStore(tmp_path / "jobs.json"))
    record, reused = registry.create_or_reuse(
        principal="principal",
        server_id="host",
        target_identity="ssh:host:fingerprint",
        idempotency_key="key",
        request_digest_value="a" * 64,
        now="2026-09-10T12:00:00Z",
    )
    assert reused is False
    same, reused = registry.create_or_reuse(
        principal="principal",
        server_id="host",
        target_identity="ssh:host:fingerprint",
        idempotency_key="key",
        request_digest_value="a" * 64,
        now="2026-09-10T12:00:01Z",
    )
    assert reused is True
    assert same.job_id == record.job_id

    with pytest.raises(AppError) as conflict:
        registry.create_or_reuse(
            principal="principal",
            server_id="host",
            target_identity="ssh:host:fingerprint",
            idempotency_key="key",
            request_digest_value="b" * 64,
            now="2026-09-10T12:00:01Z",
        )
    assert conflict.value.code == ErrorCode.CONFLICT

    with pytest.raises(AppError) as denied:
        registry.mark_lost(job_id=record.job_id, principal="other", now="2026-09-10T12:00:02Z")
    assert denied.value.code == ErrorCode.NOT_FOUND
    assert (
        registry.mark_lost(
            job_id=record.job_id, principal="principal", now="2026-09-10T12:00:02Z"
        ).state
        == "lost"
    )


class FakeProgramClient:
    stable_identity = "ssh:host:fingerprint"

    def __init__(self, result: object = "ok", error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.started = asyncio.Event()

    async def execute_program(
        self,
        executable: str,
        argv: list[str],
        cwd: str | None,
        stdin: str | None,
    ) -> object:
        self.started.set()
        await asyncio.sleep(0)
        if self.error is not None:
            raise self.error
        return {
            "executable": executable,
            "argv": argv,
            "cwd": cwd,
            "stdin": stdin,
            "result": self.result,
        }


async def wait_for_terminal(registry: ProgramJobRegistry, job_id: str) -> dict[str, object]:
    for _ in range(20):
        result = await registry.result(job_id=job_id, principal="principal")
        if result["result_available"]:
            return result
        await asyncio.sleep(0)
    raise AssertionError("job did not reach a terminal state")


@pytest.mark.asyncio
async def test_job_result_preserves_typed_inputs_and_is_owner_scoped() -> None:
    registry = ProgramJobRegistry()
    client = FakeProgramClient()

    submitted = await registry.submit(
        principal="principal",
        target="host",
        target_identity=client.stable_identity,
        client=client,
        executable="/usr/bin/id",
        argv=["--user"],
        cwd="/tmp",
        stdin="input",
    )
    await client.started.wait()
    result = await wait_for_terminal(registry, str(submitted["job_id"]))

    assert result["status"] == "succeeded"
    assert result["result"] == {
        "executable": "/usr/bin/id",
        "argv": ["--user"],
        "cwd": "/tmp",
        "stdin": "input",
        "result": "ok",
    }
    with pytest.raises(AppError) as exc_info:
        await registry.result(job_id=str(submitted["job_id"]), principal="other")
    assert exc_info.value.code == ErrorCode.NOT_FOUND
    await registry.close()


@pytest.mark.asyncio
async def test_job_failure_is_bounded_and_does_not_leak_exception_details() -> None:
    registry = ProgramJobRegistry()
    client = FakeProgramClient(error=RuntimeError("private backend detail"))

    submitted = await registry.submit(
        principal="principal",
        target="host",
        target_identity=client.stable_identity,
        client=client,
        executable="/usr/bin/id",
        argv=[],
        cwd=None,
        stdin=None,
    )
    result = await wait_for_terminal(registry, str(submitted["job_id"]))

    assert result["status"] == "failed"
    assert result["error"] == {
        "code": ErrorCode.INTERNAL.value,
        "message": "typed program job failed",
        "retryable": False,
    }
    await registry.close()


@pytest.mark.asyncio
async def test_close_cancels_pending_jobs_and_clears_registry() -> None:
    registry = ProgramJobRegistry()
    started = asyncio.Event()

    class BlockingClient(FakeProgramClient):
        async def execute_program(
            self,
            executable: str,
            argv: list[str],
            cwd: str | None,
            stdin: str | None,
        ) -> object:
            started.set()
            await asyncio.Event().wait()
            return None

    client = BlockingClient()
    submitted = await registry.submit(
        principal="principal",
        target="host",
        target_identity=client.stable_identity,
        client=client,
        executable="/usr/bin/id",
        argv=[],
        cwd=None,
        stdin=None,
    )
    await started.wait()
    await registry.close()

    with pytest.raises(AppError) as exc_info:
        await registry.status(job_id=str(submitted["job_id"]), principal="principal")
    assert exc_info.value.code == ErrorCode.NOT_FOUND


@pytest.mark.asyncio
async def test_cancel_is_owner_scoped_and_returns_terminal_status() -> None:
    registry = ProgramJobRegistry()
    started = asyncio.Event()

    class BlockingClient(FakeProgramClient):
        async def execute_program(
            self,
            executable: str,
            argv: list[str],
            cwd: str | None,
            stdin: str | None,
        ) -> object:
            started.set()
            await asyncio.Event().wait()
            return None

    client = BlockingClient()
    submitted = await registry.submit(
        principal="principal",
        target="host",
        target_identity=client.stable_identity,
        client=client,
        executable="/usr/bin/id",
        argv=[],
        cwd=None,
        stdin=None,
    )
    await started.wait()

    with pytest.raises(AppError) as exc_info:
        await registry.cancel(job_id=str(submitted["job_id"]), principal="other")
    assert exc_info.value.code == ErrorCode.NOT_FOUND

    cancelled = await registry.cancel(job_id=str(submitted["job_id"]), principal="principal")
    assert cancelled["status"] == "cancelled"
    assert cancelled["result_available"] is True
    await registry.close()


def test_registry_expires_stale_queued_records_at_retention_horizon(
    tmp_path: Path,
) -> None:
    from datetime import UTC, datetime, timedelta

    from mikrus_mcp.remote_jobs import (
        REMOTE_JOB_RETENTION_SECONDS,
        DurableRemoteJobRegistry,
        RemoteJobStore,
    )

    registry = DurableRemoteJobRegistry(RemoteJobStore(tmp_path / "jobs.json"))
    stale_now = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)
    stale, _ = registry.create_or_reuse(
        principal="principal",
        server_id="host",
        target_identity="ssh:host",
        idempotency_key="stale",
        request_digest_value="a" * 64,
        now=stale_now.isoformat(),
    )
    fresh, _ = registry.create_or_reuse(
        principal="principal",
        server_id="host",
        target_identity="ssh:host",
        idempotency_key="fresh",
        request_digest_value="b" * 64,
        now=(stale_now + timedelta(seconds=REMOTE_JOB_RETENTION_SECONDS + 2)).isoformat(),
    )

    expired_count = registry.expire_older_than(
        now=stale_now + timedelta(seconds=REMOTE_JOB_RETENTION_SECONDS + 1)
    )

    assert expired_count >= 1
    loaded_stale = registry.store.load()
    states = {item.job_id: item.state for item in loaded_stale}
    assert states[stale.job_id] == "expired"
    assert states[fresh.job_id] in {"queued", "running"}
    with pytest.raises(ValueError, match="terminal"):
        registry.update(
            job_id=stale.job_id,
            principal="principal",
            state="running",
            now=datetime.now(UTC).isoformat(),
        )
