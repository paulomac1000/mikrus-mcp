"""Bounded in-process registry for typed remote program jobs."""

from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from mikrus_mcp.errors import AppError, ErrorCode

JobState = Literal["queued", "running", "succeeded", "failed", "cancelled"]
MAX_PROGRAM_JOBS = 64
PROGRAM_JOB_TTL_SECONDS = 300.0


@dataclass(slots=True)
class _ProgramJob:
    job_id: str
    principal: str
    target: str
    target_identity: str
    created_at: float
    expires_at: float
    state: JobState = "queued"
    result: Any = None
    error: dict[str, object] | None = None
    task: asyncio.Task[None] | None = field(default=None, repr=False)


class ProgramJobRegistry:
    """Own accepted typed jobs until completion or bounded retention expiry."""

    def __init__(self) -> None:
        self._jobs: dict[str, _ProgramJob] = {}
        self._lock = asyncio.Lock()

    async def submit(
        self,
        *,
        principal: str,
        target: str,
        target_identity: str,
        client: Any,
        executable: str,
        argv: list[str],
        cwd: str | None,
        stdin: str | None,
    ) -> dict[str, object]:
        async with self._lock:
            self._purge_expired(time.monotonic())
            if len(self._jobs) >= MAX_PROGRAM_JOBS:
                raise AppError(ErrorCode.CONFLICT, "typed program job capacity is exhausted")
            now = time.monotonic()
            job = _ProgramJob(
                job_id=secrets.token_urlsafe(24),
                principal=principal,
                target=target,
                target_identity=target_identity,
                created_at=now,
                expires_at=now + PROGRAM_JOB_TTL_SECONDS,
            )
            self._jobs[job.job_id] = job
            job.task = asyncio.create_task(
                self._run(job, client, executable, argv, cwd, stdin),
                name=f"mikrus-program-job-{job.job_id}",
            )
            return self._status(job)

    async def status(self, *, job_id: str, principal: str) -> dict[str, object]:
        async with self._lock:
            job = self._owned_job(job_id, principal)
            return self._status(job)

    async def target_binding(self, *, job_id: str, principal: str) -> tuple[str, str]:
        async with self._lock:
            job = self._owned_job(job_id, principal)
            return job.target, job.target_identity

    async def result(self, *, job_id: str, principal: str) -> dict[str, object]:
        async with self._lock:
            job = self._owned_job(job_id, principal)
            response = self._status(job)
            if job.state == "succeeded":
                response["result"] = job.result
            elif job.state == "failed":
                response["error"] = job.error or {
                    "code": ErrorCode.INTERNAL.value,
                    "message": "typed program job failed",
                }
            return response

    async def cancel(self, *, job_id: str, principal: str) -> dict[str, object]:
        """Cancel an owned queued or running job and return its terminal status."""
        async with self._lock:
            job = self._owned_job(job_id, principal)
            task = job.task
            if task is None or task.done():
                return self._status(job)
            job.state = "cancelled"
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        async with self._lock:
            return self._status(self._owned_job(job_id, principal))

    async def close(self) -> None:
        async with self._lock:
            tasks = [job.task for job in self._jobs.values() if job.task is not None]
            for task in tasks:
                if task is not None and not task.done():
                    task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        async with self._lock:
            self._jobs.clear()

    async def _run(
        self,
        job: _ProgramJob,
        client: Any,
        executable: str,
        argv: list[str],
        cwd: str | None,
        stdin: str | None,
    ) -> None:
        job.state = "running"
        try:
            job.result = await client.execute_program(executable, argv, cwd, stdin)
            job.state = "succeeded"
        except asyncio.CancelledError:
            job.state = "cancelled"
            raise
        except AppError as exc:
            job.state = "failed"
            job.error = {
                "code": exc.code.value,
                "message": exc.message,
                "retryable": exc.retryable,
            }
        except Exception:
            job.state = "failed"
            job.error = {
                "code": ErrorCode.INTERNAL.value,
                "message": "typed program job failed",
                "retryable": False,
            }

    def _owned_job(self, job_id: str, principal: str) -> _ProgramJob:
        job = self._jobs.get(job_id)
        if job is None or job.principal != principal or job.expires_at <= time.monotonic():
            if job is not None and job.expires_at <= time.monotonic():
                self._jobs.pop(job_id, None)
            raise AppError(ErrorCode.NOT_FOUND, "typed program job not found")
        return job

    @staticmethod
    def _status(job: _ProgramJob) -> dict[str, object]:
        return {
            "job_id": job.job_id,
            "status": job.state,
            "target": job.target,
            "target_identity": job.target_identity,
            "result_available": job.state in {"succeeded", "failed", "cancelled"},
        }

    def _purge_expired(self, now: float) -> None:
        expired = [job_id for job_id, job in self._jobs.items() if job.expires_at <= now]
        for job_id in expired:
            job = self._jobs.pop(job_id)
            if job.task is not None and not job.task.done():
                job.task.cancel()
