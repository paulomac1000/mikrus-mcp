from __future__ import annotations

import asyncio

import pytest

from mikrus_mcp.errors import AppError, ErrorCode
from mikrus_mcp.jobs import ProgramJobRegistry


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
