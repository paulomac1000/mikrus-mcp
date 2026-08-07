"""Shared bounded adapter helpers."""

from __future__ import annotations

import asyncio
import shlex
import time
from collections.abc import Awaitable, Callable

from mikrus_mcp.validators import validate_path

_CACHEABLE_ENDPOINTS = frozenset({"/info", "/stats", "/serwery", "/porty"})
_CACHE_TTL_SECONDS = 60.0


def _remote_read_prefix(path: str) -> str:
    """Resolve a remote path and reject canonical protected locations."""
    target = shlex.quote(validate_path(path))
    return (
        f"target={target}; resolved=$(realpath -e -- \"$target\"); "
        'case "$resolved" in '
        "/etc/shadow|/etc/gshadow|/root/.ssh|/root/.ssh/*|/proc/kcore) "
        "echo 'protected path' >&2; exit 64;; "
        "esac; "
    )


def _remote_write_prefix(path: str) -> str:
    """Resolve the remote parent and bind a write to canonical safe roots."""
    target = shlex.quote(validate_path(path, for_write=True))
    return (
        f"target={target}; parent=$(dirname -- \"$target\"); "
        'leaf=$(basename -- "$target"); '
        'resolved_parent=$(realpath -e -- "$parent"); '
        'case "$resolved_parent" in '
        "/home|/home/*|/opt|/opt/*|/srv|/srv/*|/tmp|/tmp/*|"
        "/var/log|/var/log/*|/var/www|/var/www/*) ;; "
        "*) echo 'write path escaped safe roots' >&2; exit 64;; "
        "esac; "
        'target="$resolved_parent/$leaf"; test ! -L "$target"; '
    )


class RateLimiter:
    """Serialize reservations against a credential-scoped requests-per-minute quota."""

    def __init__(
        self,
        requests_per_minute: int = 5,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if requests_per_minute <= 0:
            raise ValueError("requests_per_minute must be positive")
        self._interval = 60.0 / requests_per_minute
        self._clock = clock
        self._sleep = sleep
        self._next_slot = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = self._clock()
            delay = max(0.0, self._next_slot - now)
            if delay:
                await self._sleep(delay)
                now = self._clock()
            self._next_slot = max(now, self._next_slot) + self._interval
