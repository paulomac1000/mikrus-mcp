"""Bounded cron profile records, durable store, and pure crontab projection logic.

Crontab text transformation is kept pure and unit-testable. The crontab binary
is only ever executed through the SSH-side JSON-stdin helper with typed argv
(``crontab -l`` for reads and ``crontab -`` with the new text on stdin for
installs); user values never enter shell command text.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, cast

from mikrus_mcp.errors import AppError, ErrorCode
from mikrus_mcp.validators import CRON_FIELDS

MAX_CRON_PROFILES = 64
MAX_CRONTAB_TEXT_BYTES = 1_048_576
MARKER_PREFIX = "# mikrus-mcp:"
MARKER_DIGEST_LENGTH = 64

_MARKER: Final = re.compile(r"^# mikrus-mcp:([a-z0-9][a-z0-9_-]{0,63}):sha256=([0-9a-f]{64})$")
_UNSAFE_TEXT: Final = re.compile(r"[\x00-\x1f\x7f%]")


def shell_quote_argument(value: str) -> str:
    """Strictly single-quote one typed argument for a generated cron line."""
    if _UNSAFE_TEXT.search(value):
        raise AppError(
            ErrorCode.VALIDATION,
            "argument contains characters that cannot be safely quoted (UNSAFE_ARGUMENT)",
        )
    return "'" + value.replace("'", "'\\''") + "'"


def desired_digest(generated_line: str) -> str:
    return hashlib.sha256(generated_line.encode("utf-8")).hexdigest()


def marker_line(profile_id: str, digest: str) -> str:
    return f"{MARKER_PREFIX}{profile_id}:sha256={digest}"


def generate_cron_line(
    *,
    schedule: dict[str, str],
    executable: str,
    argv: list[str],
    environment: dict[str, str],
) -> str:
    """Render the five schedule fields plus the strictly quoted typed command."""
    fields = " ".join(schedule[name] for name in CRON_FIELDS)
    quoted_environment = " ".join(
        f"{key}={shell_quote_argument(value)}" for key, value in sorted(environment.items())
    )
    quoted_argv = " ".join(
        [shell_quote_argument(executable), *(shell_quote_argument(a) for a in argv)]
    )
    command = f"{quoted_environment} {quoted_argv}".strip()
    return f"{fields} {command}"


@dataclass(slots=True)
class CronProfileRecord:
    """Owner-bound durable cron profile record."""

    profile_id: str
    principal: str
    server_id: str
    target_identity: str
    schedule: dict[str, str]
    executable: str
    argv: list[str]
    environment: dict[str, str]
    created_at: str
    updated_at: str
    desired_digest: str = field(default="")

    def with_projection(self, generated_line: str) -> CronProfileRecord:
        self.desired_digest = desired_digest(generated_line)
        return self

    def as_dict(self) -> dict[str, object]:
        return {
            "profileId": self.profile_id,
            "principal": self.principal,
            "serverId": self.server_id,
            "targetIdentity": self.target_identity,
            "schedule": dict(self.schedule),
            "executable": self.executable,
            "argv": list(self.argv),
            "environment": dict(self.environment),
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "desiredDigest": self.desired_digest,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> CronProfileRecord:
        required = (
            "profileId",
            "principal",
            "serverId",
            "targetIdentity",
            "executable",
            "createdAt",
            "updatedAt",
            "desiredDigest",
        )
        values = {key: payload.get(key) for key in required}
        if any(not isinstance(value, str) for value in values.values()):
            raise ValueError("cron profile record has invalid identity fields")
        schedule = payload.get("schedule")
        if (
            not isinstance(schedule, dict)
            or set(schedule) != set(CRON_FIELDS)
            or any(not isinstance(item, str) for item in schedule.values())
        ):
            raise ValueError("cron profile record has an invalid schedule")
        argv = payload.get("argv")
        if not isinstance(argv, list) or any(not isinstance(item, str) for item in argv):
            raise ValueError("cron profile record has invalid arguments")
        environment = payload.get("environment", {})
        if not isinstance(environment, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in environment.items()
        ):
            raise ValueError("cron profile record has an invalid environment")
        return cls(
            profile_id=cast(str, values["profileId"]),
            principal=cast(str, values["principal"]),
            server_id=cast(str, values["serverId"]),
            target_identity=cast(str, values["targetIdentity"]),
            schedule={str(key): str(value) for key, value in schedule.items()},
            executable=cast(str, values["executable"]),
            argv=[str(item) for item in argv],
            environment={str(key): str(value) for key, value in environment.items()},
            created_at=cast(str, values["createdAt"]),
            updated_at=cast(str, values["updatedAt"]),
            desired_digest=cast(str, values["desiredDigest"]),
        )


class CronProfileStore:
    """Persist bounded cron profile records in one atomically replaced JSON file."""

    def __init__(self, path: Path, *, max_records: int = MAX_CRON_PROFILES) -> None:
        if max_records < 1:
            raise ValueError("max_records must be positive")
        self.path = path
        self.max_records = max_records

    def load(self) -> list[CronProfileRecord]:
        with self._lock():
            return self._load_unlocked()

    def _load_unlocked(self) -> list[CronProfileRecord]:
        if not self.path.exists():
            return []
        if self.path.is_symlink() or not self.path.is_file():
            raise ValueError("cron profile store must be a regular file")
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, list) or len(payload) > self.max_records:
            raise ValueError("cron profile store is malformed or exceeds its bound")
        if any(not isinstance(item, dict) for item in payload):
            raise ValueError("cron profile store contains a non-object record")
        return [CronProfileRecord.from_dict(item) for item in payload]

    def find_for(self, *, principal: str, server_id: str) -> list[CronProfileRecord]:
        return [
            record
            for record in self.load()
            if record.principal == principal and record.server_id == server_id
        ]

    def get(self, *, profile_id: str, principal: str, server_id: str) -> CronProfileRecord:
        record = next(
            (
                item
                for item in self.load()
                if item.profile_id == profile_id
                and item.principal == principal
                and item.server_id == server_id
            ),
            None,
        )
        if record is None:
            raise AppError(ErrorCode.NOT_FOUND, "cron profile not found (PROFILE_NOT_FOUND)")
        return record

    def upsert(self, record: CronProfileRecord) -> CronProfileRecord:
        with self._lock():
            records = self._load_unlocked()
            for index, current in enumerate(records):
                if (
                    current.profile_id == record.profile_id
                    and current.principal == record.principal
                    and current.server_id == record.server_id
                ):
                    records[index] = record
                    replaced = True
                    break
            else:
                replaced = False
            if not replaced:
                if len(records) >= self.max_records:
                    raise ValueError("cron profile store capacity is exhausted")
                records.append(record)
            self._persist_unlocked(records)
            return record

    def delete(self, *, profile_id: str, principal: str, server_id: str) -> CronProfileRecord:
        with self._lock():
            records = self._load_unlocked()
            found = None
            remaining = []
            for current in records:
                if (
                    current.profile_id == profile_id
                    and current.principal == principal
                    and current.server_id == server_id
                ):
                    found = current
                    continue
                remaining.append(current)
            if found is None:
                raise AppError(ErrorCode.NOT_FOUND, "cron profile not found (PROFILE_NOT_FOUND)")
            self._persist_unlocked(remaining)
            return found

    def _persist_unlocked(self, records: list[CronProfileRecord]) -> None:
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

    @contextmanager
    def _lock(self) -> Iterator[None]:
        import fcntl

        if self.path.parent.is_symlink():
            raise ValueError("cron profile store parent must not be a symlink")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_name(f".{self.path.name}.lock")
        if lock_path.is_symlink():
            raise ValueError("cron profile store lock must not be a symlink")
        with lock_path.open("a+", encoding="utf-8") as lock:
            os.chmod(lock_path, 0o600)
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


class CronProfileRegistry:
    """Coordinate ownership and durable persistence over the profile store."""

    def __init__(self, store: CronProfileStore) -> None:
        self.store = store

    def get(self, *, profile_id: str, principal: str, server_id: str) -> CronProfileRecord:
        return self.store.get(profile_id=profile_id, principal=principal, server_id=server_id)

    def upsert(self, record: CronProfileRecord) -> CronProfileRecord:
        return self.store.upsert(record)

    def delete(self, *, profile_id: str, principal: str, server_id: str) -> CronProfileRecord:
        return self.store.delete(profile_id=profile_id, principal=principal, server_id=server_id)


def scan_installed(text: str) -> dict[str, list[str | None]]:
    """Map profile_id -> observed marker digests plus the adjacent following line.

    The adjacent line is the line immediately after the marker; it is the
    generated cron line for a well-formed pair. None means the marker is the
    final line of the file (malformed pair).
    """
    observed: dict[str, list[str | None]] = {}
    lines = text.split("\n")
    for index, line in enumerate(lines):
        match = _MARKER.fullmatch(line)
        if match is None:
            continue
        adjacent = lines[index + 1] if index + 1 < len(lines) else None
        observed.setdefault(match.group(1), []).append(match.group(2))
        observed.setdefault(f"{match.group(1)}:line", []).append(adjacent)
    return observed


def marker_count(observed: dict[str, list[str | None]], profile_id: str) -> int:
    return len(observed.get(profile_id, []))


def adjacent_line(observed: dict[str, list[str | None]], profile_id: str) -> str | None:
    values = observed.get(f"{profile_id}:line", [])
    return values[0] if values else None


def profile_state(
    observed: dict[str, list[str | None]],
    *,
    profile_id: str,
    generated_line: str,
    digest: str,
) -> str:
    if marker_count(observed, profile_id) > 1:
        return "DUPLICATED"
    if marker_count(observed, profile_id) == 0:
        return "MISSING"
    if adjacent_line(observed, profile_id) != generated_line or observed[profile_id][0] != digest:
        return "MODIFIED"
    return "IN_SYNC"


def _remove_pair_unlocked(text: str, profile_id: str, *, expect: bool) -> str:
    lines = text.split("\n")
    output: list[str] = []
    index = 0
    matches = 0
    while index < len(lines):
        match = _MARKER.fullmatch(lines[index])
        if match is not None and match.group(1) == profile_id:
            matches += 1
            index += 2  # drop the marker line and its adjacent generated line
            continue
        output.append(lines[index])
        index += 1
    if matches == 0 and expect:
        raise AppError(ErrorCode.NOT_FOUND, "cron profile marker is absent (PROFILE_NOT_FOUND)")
    if matches > 1:
        raise AppError(
            ErrorCode.CONFLICT,
            "installed crontab contains duplicate markers (DUPLICATE_MARKER)",
        )
    return "\n".join(output)


def upsert_in_text(text: str, *, profile_id: str, generated_line: str, digest: str) -> str:
    """Idempotently replace the marker plus generated-line pair for one profile."""
    without = _remove_pair_unlocked(text, profile_id, expect=False)
    marker = marker_line(profile_id, digest)
    if without == "":
        return f"{marker}\n{generated_line}\n"
    if without.endswith("\n"):
        return f"{without}{marker}\n{generated_line}\n"
    return f"{without}\n{marker}\n{generated_line}\n"


def remove_from_text(text: str, *, profile_id: str) -> str:
    """Remove exactly the marker plus generated-line pair for one profile."""
    return _remove_pair_unlocked(text, profile_id, expect=True)


def validate_installed_text(text: str) -> str:
    """Reject unbounded or binary crontab payloads before transformation."""
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_CRONTAB_TEXT_BYTES:
        raise AppError(
            ErrorCode.UPSTREAM,
            "crontab text exceeds the bounded read limit (CRONTAB_READ_FAILED)",
        )
    if "\x00" in text:
        raise AppError(
            ErrorCode.UPSTREAM,
            "crontab text contains invalid bytes (CRONTAB_READ_FAILED)",
        )
    return text
