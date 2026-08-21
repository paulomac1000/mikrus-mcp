"""Shared bounded adapter helpers."""

from __future__ import annotations

import asyncio
import base64
import shlex
import time
from collections.abc import Callable

from mikrus_mcp.errors import AppError, ErrorCode
from mikrus_mcp.validators import validate_content_size, validate_path

_CACHEABLE_ENDPOINTS = frozenset({"/info", "/stats", "/serwery", "/porty"})
_CACHE_TTL_SECONDS = 60.0


def _remote_read_prefix(path: str) -> str:
    """Resolve a remote path and reject canonical protected locations."""
    target = shlex.quote(validate_path(path))
    return (
        f'target={target}; resolved=$(realpath -e -- "$target"); '
        'case "$resolved" in '
        "/etc/shadow|/etc/gshadow|/root/.ssh|/root/.ssh/*|/proc/kcore) "
        "echo 'protected path' >&2; exit 64;; "
        "esac; "
    )


_REMOTE_ATOMIC_WRITE = r"""
import base64
import os
import stat
import sys

path = os.path.normpath(sys.argv[1])
encoded = sys.argv[2]
roots = ("/home", "/opt", "/srv", "/tmp", "/var/log", "/var/www")
if not path.startswith("/") or path == "/" or not any(
    path == root or path.startswith(root + "/") for root in roots
):
    raise SystemExit("write path escaped safe roots")
parts = [part for part in path.split("/") if part]
if not parts or any(part in {".", ".."} for part in parts):
    raise SystemExit("invalid write path")
*directories, leaf = parts
no_follow = getattr(os, "O_NOFOLLOW", 0)
directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | no_follow
parent_fd = os.open("/", directory_flags)
opened = [parent_fd]
temporary = None
try:
    for component in directories:
        child = os.open(component, directory_flags, dir_fd=parent_fd)
        opened.append(child)
        parent_fd = child
    try:
        metadata = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise SystemExit("write target must be a regular non-symlink file")
    payload = base64.b64decode(encoded, validate=True)
    temporary = f".{leaf}.mcp.{os.getpid()}.{os.urandom(8).hex()}"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | no_follow,
        0o600,
        dir_fd=parent_fd,
    )
    try:
        view = memoryview(payload)
        written = 0
        while written < len(view):
            written += os.write(descriptor, view[written:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(
        temporary,
        leaf,
        src_dir_fd=parent_fd,
        dst_dir_fd=parent_fd,
    )
    temporary = None
    os.fsync(parent_fd)
finally:
    if temporary is not None:
        try:
            os.unlink(temporary, dir_fd=parent_fd)
        except FileNotFoundError:
            pass
    for descriptor in reversed(opened):
        os.close(descriptor)
print("WRITE_OK")
""".strip()


def _remote_atomic_write_command(path: str, content: str) -> str:
    """Return a shell-safe command which performs a no-follow dir-fd atomic write."""
    target = validate_path(path, for_write=True)
    validate_content_size(content)
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    return (
        "python3 -c "
        + shlex.quote(_REMOTE_ATOMIC_WRITE)
        + " "
        + shlex.quote(target)
        + " "
        + shlex.quote(encoded)
    )


class RateLimiter:
    """Reserve credential-scoped request slots without consuming operation deadlines."""

    def __init__(
        self,
        requests_per_minute: int = 5,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if requests_per_minute <= 0:
            raise ValueError("requests_per_minute must be positive")
        self._interval = 60.0 / requests_per_minute
        self._clock = clock
        self._next_slot = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = self._clock()
            delay = max(0.0, self._next_slot - now)
            if delay > 0:
                raise AppError(
                    ErrorCode.RATE_LIMITED,
                    "local credential rate limit requires a later request slot",
                    retry_after_seconds=min(60.0, delay),
                )
            self._next_slot = now + self._interval
