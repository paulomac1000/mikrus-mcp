"""Persistent one-time server-side approval records."""

from __future__ import annotations

import json
import os
import secrets
import stat
import threading
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    capability: str
    principal: str
    target: str
    resource: str
    expires_at: float


class ApprovalRegistry:
    """Bounded one-time approvals loaded from a protected administrator-owned file."""

    def __init__(
        self,
        records: dict[str, ApprovalRecord] | None = None,
        max_records: int = 1_024,
        *,
        source_path: Path | None = None,
    ) -> None:
        if not 1 <= max_records <= 10_000:
            raise ValueError("max_records must be between 1 and 10000")
        records = dict(records or {})
        if len(records) > max_records:
            raise ValueError("approval record count exceeds configured capacity")
        self._records = records
        self._max_records = max_records
        self._source_path = source_path
        self._source_identity = self._identity(source_path) if source_path else None
        self._lock = threading.Lock()

    @classmethod
    def from_file(cls, path: Path | None) -> "ApprovalRegistry":
        if path is None:
            return cls()
        if path.is_symlink() or not path.is_file():
            raise ValueError("approval file must be a regular non-symlink file")
        metadata = path.stat()
        if metadata.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise ValueError("approval file permissions are too broad")
        if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
            raise ValueError("approval file must be owned by the current process user")
        if path.stat().st_size > 1_048_576:
            raise ValueError("approval file exceeds one MiB")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("approval file is unreadable or invalid JSON") from exc
        if not isinstance(raw, dict) or not isinstance(raw.get("tokens", {}), dict):
            raise ValueError("approval file must contain a tokens object")
        records: dict[str, ApprovalRecord] = {}
        for token, value in raw.get("tokens", {}).items():
            if not isinstance(token, str) or len(token) < 32 or not isinstance(value, dict):
                raise ValueError("approval token entries are invalid")
            try:
                record = ApprovalRecord(
                    capability=str(value["capability"]),
                    principal=str(value["principal"]),
                    target=str(value["target"]),
                    resource=str(value["resource"]),
                    expires_at=float(value["expires_at"]),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("approval record is invalid") from exc
            records[token] = record
        registry = cls(records, source_path=path.resolve())
        with registry._lock:
            registry._persist_locked()
        return registry

    @staticmethod
    def _identity(path: Path) -> tuple[int, int]:
        metadata = path.stat(follow_symlinks=False)
        return metadata.st_dev, metadata.st_ino

    def _persist_locked(self) -> None:
        if self._source_path is None:
            return
        if self._source_path.is_symlink() or not self._source_path.is_file():
            raise RuntimeError("approval file identity is no longer valid")
        if self._source_identity != self._identity(self._source_path):
            raise RuntimeError("approval file identity changed")
        payload = {
            "tokens": {
                token: {
                    "capability": record.capability,
                    "principal": record.principal,
                    "target": record.target,
                    "resource": record.resource,
                    "expires_at": record.expires_at,
                }
                for token, record in sorted(self._records.items())
            }
        }
        encoded = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode()
        temporary = self._source_path.with_name(
            f".{self._source_path.name}.{secrets.token_hex(16)}.tmp"
        )
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.close(descriptor)
            descriptor = -1
            if self._source_identity != self._identity(self._source_path):
                raise RuntimeError("approval file identity changed before replacement")
            os.replace(temporary, self._source_path)
            self._source_identity = self._identity(self._source_path)
            if os.name != "nt":
                directory = os.open(self._source_path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temporary.exists():
                temporary.unlink()

    def issue_for_test(
        self,
        capability: str,
        principal: str,
        target: str,
        resource: str,
        *,
        ttl_seconds: float = 60.0,
    ) -> str:
        """Issue a record for trusted embedding hosts and deterministic tests only."""
        if not 0 < ttl_seconds <= 300:
            raise ValueError("approval ttl must be between 0 and 300 seconds")
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._purge_locked(time.time())
            if len(self._records) >= self._max_records:
                raise RuntimeError("approval registry capacity reached")
            self._records[token] = ApprovalRecord(
                capability, principal, target, resource, time.time() + ttl_seconds
            )
        return token

    def _purge_locked(self, now: float) -> None:
        for token in [key for key, value in self._records.items() if value.expires_at < now]:
            self._records.pop(token, None)

    def consume(
        self,
        token: str | None,
        capability: str,
        principal: str,
        target: str,
        resource: str,
    ) -> bool:
        if not isinstance(token, str) or not token:
            return False
        now = time.time()
        with self._lock:
            self._purge_locked(now)
            record = self._records.pop(token, None)
            matched = (
                record is not None
                and record.capability == capability
                and record.principal == principal
                and record.target == target
                and record.resource == resource
                and record.expires_at >= now
            )
            try:
                self._persist_locked()
            except OSError as exc:
                raise RuntimeError("approval consumption could not be persisted") from exc
        return matched
