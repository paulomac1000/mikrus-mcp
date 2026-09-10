"""Bounded, serializable contract for durable remote operation records.

This module deliberately contains no executor or persistence implementation.  It
is the stable record shape shared by the future durable job store and adapters.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, cast

from mikrus_mcp.errors import AppError, ErrorCode

RemoteJobState = Literal["queued", "running", "succeeded", "failed", "cancelled", "lost", "expired"]
_TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled", "lost", "expired"})
MAX_REMOTE_OUTPUT_BYTES = 1_000_000
MAX_REMOTE_ERROR_BYTES = 8_192


def request_digest(payload: object) -> str:
    """Return a stable SHA-256 digest for an idempotency-bound request."""
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


@dataclass(slots=True)
class RemoteJobRecord:
    """Machine-readable remote job identity and bounded terminal state."""

    job_id: str
    principal: str
    server_id: str
    target_identity: str
    idempotency_key: str
    request_digest: str
    created_at: str
    last_progress_at: str
    state: RemoteJobState = "queued"
    started_at: str | None = None
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    stdout_offset: int = 0
    stderr_offset: int = 0
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    safe_to_retry: bool = False
    runtime_identity: dict[str, str] = field(default_factory=dict)
    error: str | None = None

    @classmethod
    def create(
        cls,
        *,
        principal: str,
        server_id: str,
        target_identity: str,
        idempotency_key: str,
        request_digest_value: str,
        now: str,
    ) -> RemoteJobRecord:
        return cls(
            job_id=secrets.token_urlsafe(24),
            principal=principal,
            server_id=server_id,
            target_identity=target_identity,
            idempotency_key=idempotency_key,
            request_digest=request_digest_value,
            created_at=now,
            last_progress_at=now,
        )

    @property
    def terminal(self) -> bool:
        return self.state in _TERMINAL_STATES

    def transition(self, state: RemoteJobState, *, now: str) -> None:
        if self.terminal and state != self.state:
            raise ValueError("terminal remote job cannot transition")
        if state == "queued" and self.state != "queued":
            raise ValueError("remote job cannot return to queued")
        self.state = state
        self.last_progress_at = now
        if state == "running" and self.started_at is None:
            self.started_at = now

    def append_output(self, *, stream: Literal["stdout", "stderr"], chunk: str) -> None:
        if not isinstance(chunk, str):
            raise TypeError("remote output chunk must be text")
        current = self.stdout if stream == "stdout" else self.stderr
        encoded = (current + chunk).encode("utf-8")
        if len(encoded) > MAX_REMOTE_OUTPUT_BYTES:
            encoded = encoded[-MAX_REMOTE_OUTPUT_BYTES:]
            value = encoded.decode("utf-8", errors="replace")
            if stream == "stdout":
                self.stdout, self.stdout_truncated = value, True
            else:
                self.stderr, self.stderr_truncated = value, True
            return
        if stream == "stdout":
            self.stdout = encoded.decode("utf-8")
        else:
            self.stderr = encoded.decode("utf-8")

    def as_dict(self) -> dict[str, object]:
        error = self.error
        if error is not None:
            error = error[:MAX_REMOTE_ERROR_BYTES]
        return {
            "jobId": self.job_id,
            "serverId": self.server_id,
            "state": self.state,
            "principal": self.principal,
            "targetIdentity": self.target_identity,
            "idempotencyKey": self.idempotency_key,
            "requestDigest": self.request_digest,
            "createdAt": self.created_at,
            "startedAt": self.started_at,
            "lastProgressAt": self.last_progress_at,
            "exitCode": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "stdoutOffset": self.stdout_offset,
            "stderrOffset": self.stderr_offset,
            "stdoutTruncated": self.stdout_truncated,
            "stderrTruncated": self.stderr_truncated,
            "safeToRetry": self.safe_to_retry,
            "runtimeIdentity": dict(self.runtime_identity),
            "error": error,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> RemoteJobRecord:
        required = (
            "jobId",
            "serverId",
            "state",
            "principal",
            "targetIdentity",
            "idempotencyKey",
            "requestDigest",
            "createdAt",
            "lastProgressAt",
        )
        values = {key: payload.get(key) for key in required}
        if any(not isinstance(value, str) for value in values.values()):
            raise ValueError("remote job record has invalid identity fields")
        job_id = cast(str, values["jobId"])
        server_id = cast(str, values["serverId"])
        state_value = cast(str, values["state"])
        if state_value not in {"queued", "running", *_TERMINAL_STATES}:
            raise ValueError("remote job record has an invalid state")
        state = cast(RemoteJobState, state_value)
        runtime_identity = payload.get("runtimeIdentity", {})
        if not isinstance(runtime_identity, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in runtime_identity.items()
        ):
            raise ValueError("remote job runtime identity must be string-valued")
        started_value = payload.get("startedAt")
        exit_code_value = payload.get("exitCode")
        stdout_offset_value = payload.get("stdoutOffset", 0)
        stderr_offset_value = payload.get("stderrOffset", 0)
        error_value = payload.get("error")
        return cls(
            job_id=job_id,
            principal=cast(str, values["principal"]),
            server_id=server_id,
            target_identity=cast(str, values["targetIdentity"]),
            idempotency_key=cast(str, values["idempotencyKey"]),
            request_digest=cast(str, values["requestDigest"]),
            created_at=cast(str, values["createdAt"]),
            last_progress_at=cast(str, values["lastProgressAt"]),
            state=state,
            started_at=started_value if isinstance(started_value, str) else None,
            exit_code=exit_code_value if isinstance(exit_code_value, int) else None,
            stdout=str(payload.get("stdout", "")),
            stderr=str(payload.get("stderr", "")),
            stdout_offset=stdout_offset_value if isinstance(stdout_offset_value, int) else 0,
            stderr_offset=stderr_offset_value if isinstance(stderr_offset_value, int) else 0,
            stdout_truncated=bool(payload.get("stdoutTruncated", False)),
            stderr_truncated=bool(payload.get("stderrTruncated", False)),
            safe_to_retry=bool(payload.get("safeToRetry", False)),
            runtime_identity=runtime_identity,
            error=error_value if isinstance(error_value, str) else None,
        )


class RemoteJobStore:
    """Persist bounded remote job records in one atomically replaced JSON file."""

    def __init__(self, path: Path, *, max_records: int = 256) -> None:
        if max_records < 1:
            raise ValueError("max_records must be positive")
        self.path = path
        self.max_records = max_records

    def load(self) -> list[RemoteJobRecord]:
        with self._lock():
            return self._load_unlocked()

    def _load_unlocked(self) -> list[RemoteJobRecord]:
        if not self.path.exists():
            return []
        if self.path.is_symlink() or not self.path.is_file():
            raise ValueError("remote job store must be a regular file")
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, list) or len(payload) > self.max_records:
            raise ValueError("remote job store is malformed or exceeds its bound")
        if any(not isinstance(item, dict) for item in payload):
            raise ValueError("remote job store contains a non-object record")
        return [RemoteJobRecord.from_dict(item) for item in payload]

    def find_idempotent(
        self, *, principal: str, server_id: str, idempotency_key: str
    ) -> RemoteJobRecord | None:
        with self._lock():
            return next(
                (
                    record
                    for record in self._load_unlocked()
                    if record.principal == principal
                    and record.server_id == server_id
                    and record.idempotency_key == idempotency_key
                ),
                None,
            )

    def save(self, record: RemoteJobRecord) -> None:
        with self._lock():
            records = self._load_unlocked()
            replaced = False
            for index, current in enumerate(records):
                if current.job_id == record.job_id:
                    records[index] = record
                    replaced = True
                    break
            if not replaced:
                if len(records) >= self.max_records:
                    raise ValueError("remote job store capacity is exhausted")
                records.append(record)
            fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump([item.as_dict() for item in records], stream, ensure_ascii=False)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)

    def insert_or_existing(self, record: RemoteJobRecord) -> RemoteJobRecord:
        with self._lock():
            records = self._load_unlocked()
            for current in records:
                if (
                    current.principal == record.principal
                    and current.server_id == record.server_id
                    and current.idempotency_key == record.idempotency_key
                ):
                    return current
            if len(records) >= self.max_records:
                raise ValueError("remote job store capacity is exhausted")
            records.append(record)
            fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump([item.as_dict() for item in records], stream, ensure_ascii=False)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            return record

    @contextmanager
    def _lock(self) -> Iterator[None]:
        import fcntl

        if self.path.parent.is_symlink():
            raise ValueError("remote job store parent must not be a symlink")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_name(f".{self.path.name}.lock")
        if lock_path.is_symlink():
            raise ValueError("remote job store lock must not be a symlink")
        with lock_path.open("a+", encoding="utf-8") as lock:
            os.chmod(lock_path, 0o600)
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


class DurableRemoteJobRegistry:
    """Coordinate ownership, idempotency, and state updates over a job store."""

    def __init__(self, store: RemoteJobStore) -> None:
        self.store = store

    def create_or_reuse(
        self,
        *,
        principal: str,
        server_id: str,
        target_identity: str,
        idempotency_key: str,
        request_digest_value: str,
        now: str,
    ) -> tuple[RemoteJobRecord, bool]:
        candidate = RemoteJobRecord.create(
            principal=principal,
            server_id=server_id,
            target_identity=target_identity,
            idempotency_key=idempotency_key,
            request_digest_value=request_digest_value,
            now=now,
        )
        existing = self.store.insert_or_existing(candidate)
        if existing.job_id == candidate.job_id:
            return existing, False
        if existing is not None:
            if (
                existing.request_digest != request_digest_value
                or existing.target_identity != target_identity
            ):
                raise AppError(
                    ErrorCode.CONFLICT,
                    "idempotency key is bound to a different remote job request",
                )
            return existing, True
        return existing, True

    def get(self, *, job_id: str, principal: str) -> RemoteJobRecord:
        record = next(
            (
                item
                for item in self.store.load()
                if item.job_id == job_id and item.principal == principal
            ),
            None,
        )
        if record is None:
            raise AppError(ErrorCode.NOT_FOUND, "remote job not found")
        return record

    def update(
        self,
        *,
        job_id: str,
        principal: str,
        state: RemoteJobState,
        now: str,
        exit_code: int | None = None,
        safe_to_retry: bool | None = None,
        error: str | None = None,
    ) -> RemoteJobRecord:
        record = self.get(job_id=job_id, principal=principal)
        record.transition(state, now=now)
        if exit_code is not None:
            record.exit_code = exit_code
        if safe_to_retry is not None:
            record.safe_to_retry = safe_to_retry
        if error is not None:
            record.error = error[:MAX_REMOTE_ERROR_BYTES]
        self.store.save(record)
        return record

    def mark_lost(self, *, job_id: str, principal: str, now: str) -> RemoteJobRecord:
        return self.update(
            job_id=job_id,
            principal=principal,
            state="lost",
            now=now,
            safe_to_retry=False,
        )

    def expire(self, *, job_id: str, principal: str, now: str) -> RemoteJobRecord:
        return self.update(
            job_id=job_id,
            principal=principal,
            state="expired",
            now=now,
            safe_to_retry=False,
        )
