"""Deterministic application validation used before network or privileged I/O."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Final

from mikrus_mcp.tools.constants import (
    MAX_GREP_HOURS,
    MAX_TAIL_LINES,
    MAX_WRITE_SIZE,
    SERVICE_ACTIONS,
)


class ValidationError(ValueError):
    """Input does not satisfy the local application contract."""


class WriteOperationsDisabledError(ValidationError):
    """Compatibility exception retained for callers of the old write gate."""


_PATH_CONTROL: Final = re.compile(r"[\x00-\x1f\x7f]")
_SERVICE: Final = re.compile(r"^[A-Za-z0-9_@.-]{1,255}$")
_CONTAINER: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_DOMAIN: Final = re.compile(
    r"^(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$"
)
_SEARCH: Final = re.compile(r"^[A-Za-z0-9_./:@\s-]{1,1000}$")
_USERNAME: Final = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
_PROCESS: Final = re.compile(r"^(?:[1-9][0-9]{0,9}|[A-Za-z0-9_-]{1,128})$")
_PROGRAM_CONTROL: Final = re.compile(r"[\x00-\x1f\x7f]")
_PROGRAM_JOB: Final = re.compile(r"^[A-Za-z0-9_-]{32}$")

_READ_DENIED: Final = tuple(
    PurePosixPath(value)
    for value in (
        "/etc/shadow",
        "/etc/gshadow",
        "/root/.ssh",
        "/proc/kcore",
    )
)
_WRITE_DENIED: Final = tuple(
    PurePosixPath(value)
    for value in (
        "/etc",
        "/boot",
        "/dev",
        "/proc",
        "/root",
        "/sys",
    )
)
_WRITE_ROOTS: Final = tuple(
    PurePosixPath(value)
    for value in (
        "/home",
        "/opt",
        "/srv",
        "/tmp",
        "/var/log",
        "/var/www",
    )
)


def _within(path: PurePosixPath, parent: PurePosixPath) -> bool:
    return path == parent or parent in path.parents


def validate_path(path: str, *, for_write: bool = False) -> str:
    if not isinstance(path, str) or not path:
        raise ValidationError("Path must be a non-empty string")
    if not path.startswith("/") or _PATH_CONTROL.search(path):
        raise ValidationError("Path must be an absolute POSIX path without control characters")
    raw = PurePosixPath(path)
    if any(part in {"..", "~"} for part in raw.parts):
        raise ValidationError("Path traversal is not allowed")
    normalized = PurePosixPath("/", *[part for part in raw.parts if part not in {"/", "."}])
    denied = _WRITE_DENIED if for_write else _READ_DENIED
    if any(_within(normalized, root) for root in denied):
        raise ValidationError(f"Access to '{normalized}' is forbidden")
    if for_write and not any(_within(normalized, root) for root in _WRITE_ROOTS):
        raise ValidationError(f"Writes to '{normalized}' are outside the configured safe roots")
    return str(normalized)


def validate_port(port: str | int) -> int:
    try:
        value = int(port)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Port must be a number") from exc
    if not 1 <= value <= 65_535:
        raise ValidationError("Port must be 1-65535")
    return value


def validate_service_name(name: str) -> str:
    if not isinstance(name, str) or not _SERVICE.fullmatch(name):
        raise ValidationError("Invalid service name")
    return name


def validate_service_action(action: str) -> str:
    if action not in SERVICE_ACTIONS:
        raise ValidationError(f"Invalid action: {action}")
    return action


def validate_container_name(name: str) -> str:
    if not isinstance(name, str) or not _CONTAINER.fullmatch(name):
        raise ValidationError("Invalid container name")
    return name


def validate_domain(domain: str) -> str:
    if domain == "-":
        return domain
    if not isinstance(domain, str) or len(domain) > 253 or not _DOMAIN.fullmatch(domain):
        raise ValidationError("Invalid domain")
    return domain


def validate_search_pattern(pattern: str) -> str:
    if not isinstance(pattern, str) or not _SEARCH.fullmatch(pattern):
        raise ValidationError("Invalid search pattern")
    return pattern


def validate_username(username: str) -> str:
    if not isinstance(username, str) or not _USERNAME.fullmatch(username):
        raise ValidationError("Invalid username")
    return username


def validate_process_target(target: str) -> str:
    if not isinstance(target, str) or not _PROCESS.fullmatch(target):
        raise ValidationError("Invalid process target")
    return target


def validate_program_executable(executable: str) -> str:
    if (
        not isinstance(executable, str)
        or not executable
        or len(executable) > 255
        or _PROGRAM_CONTROL.search(executable)
    ):
        raise ValidationError("executable must be a non-empty string without control characters")
    return executable


def validate_program_arguments(argv: object) -> list[str]:
    if not isinstance(argv, list) or len(argv) > 128:
        raise ValidationError("argv must be a list containing at most 128 strings")
    result: list[str] = []
    total = 0
    for value in argv:
        if not isinstance(value, str) or len(value) > 4_096 or _PROGRAM_CONTROL.search(value):
            raise ValidationError("argv entries must be strings without control characters")
        total += len(value.encode("utf-8"))
        if total > 100_000:
            raise ValidationError("argv exceeds the 100000-byte limit")
        result.append(value)
    return result


def validate_program_job_id(job_id: str) -> str:
    if not isinstance(job_id, str) or not _PROGRAM_JOB.fullmatch(job_id):
        raise ValidationError("job_id must be a valid typed program job handle")
    return job_id


def validate_content_size(content: str, max_size: int = MAX_WRITE_SIZE) -> None:
    if not isinstance(content, str):
        raise ValidationError("Content must be a string")
    size = len(content.encode("utf-8"))
    if size > max_size:
        raise ValidationError(f"Content too large: {size} bytes (max {max_size})")


def validate_lines_param(lines: int | str, max_lines: int = MAX_TAIL_LINES) -> int:
    try:
        value = int(lines)
    except (TypeError, ValueError) as exc:
        raise ValidationError("lines must be an integer") from exc
    if not 1 <= value <= max_lines:
        raise ValidationError(f"lines must be between 1 and {max_lines}")
    return value


def validate_hours_param(hours: int | str, max_hours: int = MAX_GREP_HOURS) -> int:
    try:
        value = int(hours)
    except (TypeError, ValueError) as exc:
        raise ValidationError("hours must be an integer") from exc
    if not 1 <= value <= max_hours:
        raise ValidationError(f"hours must be between 1 and {max_hours}")
    return value


def check_write_enabled() -> None:
    """Deprecated compatibility hook; write policy is enforced by InvocationKernel."""
    raise WriteOperationsDisabledError(
        "Direct write-gate calls are unsupported; invoke through InvocationKernel"
    )
