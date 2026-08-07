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
from typing import Final

_MAX_APPROVAL_FILE_BYTES: Final = 1_048_576


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    capability: str
    principal: str
    target: str
    resource: str
    expires_at: float


@dataclass(frozen=True, slots=True)
class _FileIdentity:
    device: int
    inode: int
    modified_ns: int
    size: int


class ApprovalRegistry:
    """Bounded one-time approvals backed by an owner-only JSON file.

    The file may be atomically replaced by a trusted operator. Every lookup checks
    its identity and reloads a changed file after verifying ownership, permissions,
    size, regular-file type, and the absence of a final-component symlink.
    """

    def __init__(
        self,
        records: dict[str, ApprovalRecord] | None = None,
        max_records: int = 1_024,
        *,
        source_path: Path | None = None,
        source_identity: _FileIdentity | None = None,
    ) -> None:
        if not 1 <= max_records <= 10_000:
            raise ValueError("max_records must be between 1 and 10000")
        records = dict(records or {})
        if len(records) > max_records:
            raise ValueError("approval record count exceeds configured capacity")
        self._records = records
        self._max_records = max_records
        self._source_path = source_path
        self._source_identity = source_identity
        self._lock = threading.Lock()

    @classmethod
    def from_file(cls, path: Path | None) -> ApprovalRegistry:
        if path is None:
            return cls()
        if path.is_symlink():
            raise ValueError("approval file must be a regular non-symlink file")
        resolved = path.resolve(strict=True)
        records, identity = cls._read_file(resolved, max_records=1_024)
        return cls(
            records,
            source_path=resolved,
            source_identity=identity,
        )

    @staticmethod
    def _identity(metadata: os.stat_result) -> _FileIdentity:
        return _FileIdentity(
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mtime_ns,
            metadata.st_size,
        )

    @staticmethod
    def _validate_metadata(metadata: os.stat_result) -> None:
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("approval file must be a regular non-symlink file")
        if metadata.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise ValueError("approval file permissions are too broad")
        if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
            raise ValueError("approval file must be owned by the current process user")
        if metadata.st_size > _MAX_APPROVAL_FILE_BYTES:
            raise ValueError("approval file exceeds one MiB")

    @classmethod
    def _parse_records(
        cls,
        encoded: bytes,
        *,
        max_records: int,
    ) -> dict[str, ApprovalRecord]:
        try:
            raw = json.loads(encoded.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("approval file is unreadable or invalid JSON") from exc
        if not isinstance(raw, dict) or not isinstance(raw.get("tokens", {}), dict):
            raise ValueError("approval file must contain a tokens object")
        tokens = raw.get("tokens", {})
        if len(tokens) > max_records:
            raise ValueError("approval record count exceeds configured capacity")
        records: dict[str, ApprovalRecord] = {}
        for token, value in tokens.items():
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
            if not all(
                (
                    record.capability,
                    record.principal,
                    record.target,
                    record.resource,
                )
            ):
                raise ValueError("approval record fields must be non-empty")
            records[token] = record
        return records

    @classmethod
    def _read_file(
        cls,
        path: Path,
        *,
        max_records: int,
    ) -> tuple[dict[str, ApprovalRecord], _FileIdentity]:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise ValueError("approval file is unreadable or invalid") from exc
        try:
            metadata = os.fstat(descriptor)
            cls._validate_metadata(metadata)
            path_metadata = path.stat(follow_symlinks=False)
            if (metadata.st_dev, metadata.st_ino) != (
                path_metadata.st_dev,
                path_metadata.st_ino,
            ):
                raise ValueError("approval file changed while it was opened")
            chunks: list[bytes] = []
            remaining = _MAX_APPROVAL_FILE_BYTES + 1
            while remaining:
                chunk = os.read(descriptor, min(65_536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            encoded = b"".join(chunks)
            if len(encoded) > _MAX_APPROVAL_FILE_BYTES:
                raise ValueError("approval file exceeds one MiB")
            records = cls._parse_records(encoded, max_records=max_records)
            return records, cls._identity(metadata)
        finally:
            os.close(descriptor)

    def _path_identity_locked(self) -> _FileIdentity:
        if self._source_path is None:
            raise RuntimeError("approval registry has no source file")
        if self._source_path.is_symlink():
            raise RuntimeError("approval file identity is no longer valid")
        try:
            metadata = self._source_path.stat(follow_symlinks=False)
            self._validate_metadata(metadata)
        except (OSError, ValueError) as exc:
            raise RuntimeError("approval file identity is no longer valid") from exc
        return self._identity(metadata)

    def _reload_locked(self) -> bool:
        if self._source_path is None:
            return False
        current = self._path_identity_locked()
        if current == self._source_identity:
            return False
        records, identity = self._read_file(
            self._source_path,
            max_records=self._max_records,
        )
        self._records = records
        self._source_identity = identity
        return True

    def reload(self) -> bool:
        """Reload a securely replaced approval file, returning whether it changed."""
        with self._lock:
            return self._reload_locked()

    @staticmethod
    def _payload(records: dict[str, ApprovalRecord]) -> bytes:
        payload = {
            "tokens": {
                token: {
                    "capability": record.capability,
                    "principal": record.principal,
                    "target": record.target,
                    "resource": record.resource,
                    "expires_at": record.expires_at,
                }
                for token, record in sorted(records.items())
            }
        }
        return (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8")

    def _persist_records_locked(self, records: dict[str, ApprovalRecord]) -> None:
        if self._source_path is None:
            self._records = records
            return
        expected = self._source_identity
        if expected is None or self._path_identity_locked() != expected:
            raise RuntimeError("approval file changed; reload and retry")
        temporary = self._source_path.with_name(
            f".{self._source_path.name}.{secrets.token_hex(16)}.tmp"
        )
        descriptor = -1
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(temporary, flags, 0o600)
            encoded = self._payload(records)
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.close(descriptor)
            descriptor = -1
            if self._path_identity_locked() != expected:
                raise RuntimeError("approval file changed before persisted consumption")
            os.replace(temporary, self._source_path)
            self._source_identity = self._path_identity_locked()
            self._records = records
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

    def issue(
        self,
        capability: str,
        principal: str,
        target: str,
        resource: str,
        *,
        ttl_seconds: float = 60.0,
    ) -> str:
        """Issue a record from a trusted local operator or embedding host."""
        if not 0 < ttl_seconds <= 300:
            raise ValueError("approval ttl must be between 0 and 300 seconds")
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._reload_locked()
            now = time.time()
            records = self._without_expired(self._records, now)
            if len(records) >= self._max_records:
                raise RuntimeError("approval registry capacity reached")
            records[token] = ApprovalRecord(
                capability,
                principal,
                target,
                resource,
                now + ttl_seconds,
            )
            self._persist_records_locked(records)
        return token

    def issue_for_test(
        self,
        capability: str,
        principal: str,
        target: str,
        resource: str,
        *,
        ttl_seconds: float = 60.0,
    ) -> str:
        """Compatibility wrapper for deterministic tests."""
        return self.issue(
            capability,
            principal,
            target,
            resource,
            ttl_seconds=ttl_seconds,
        )

    @staticmethod
    def _without_expired(
        records: dict[str, ApprovalRecord],
        now: float,
    ) -> dict[str, ApprovalRecord]:
        return {
            token: record
            for token, record in records.items()
            if record.expires_at >= now
        }

    @staticmethod
    def _matches(
        record: ApprovalRecord,
        capability: str,
        principal: str,
        target: str,
        resource: str,
        now: float,
    ) -> bool:
        return (
            record.capability == capability
            and record.principal == principal
            and record.target == target
            and record.resource == resource
            and record.expires_at >= now
        )

    def has_matching(
        self,
        capability: str,
        principal: str,
        target: str,
        resource: str,
    ) -> bool:
        """Check for a bound approval without consuming it."""
        now = time.time()
        with self._lock:
            self._reload_locked()
            return any(
                self._matches(record, capability, principal, target, resource, now)
                for record in self._records.values()
            )

    def consume_matching(
        self,
        capability: str,
        principal: str,
        target: str,
        resource: str,
    ) -> bool:
        """Atomically consume one matching approval immediately before execution."""
        now = time.time()
        with self._lock:
            self._reload_locked()
            active = self._without_expired(self._records, now)
            candidates = [
                (token, record)
                for token, record in active.items()
                if self._matches(record, capability, principal, target, resource, now)
            ]
            if not candidates:
                return False
            token, _ = min(candidates, key=lambda item: (item[1].expires_at, item[0]))
            active.pop(token)
            self._persist_records_locked(active)
            return True

    def consume(
        self,
        token: str | None,
        capability: str,
        principal: str,
        target: str,
        resource: str,
    ) -> bool:
        """Consume one explicit token for trusted non-MCP integrations and tests."""
        if not isinstance(token, str) or not token:
            return False
        now = time.time()
        with self._lock:
            self._reload_locked()
            active = self._without_expired(self._records, now)
            record = active.get(token)
            if record is None or not self._matches(
                record,
                capability,
                principal,
                target,
                resource,
                now,
            ):
                return False
            active.pop(token)
            self._persist_records_locked(active)
            return True
