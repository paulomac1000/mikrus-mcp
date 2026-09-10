"""Deterministic application validation used before network or privileged I/O."""

from __future__ import annotations

import base64
import binascii
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
_CRON_PROFILE_ID: Final = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_CRON_ENV_NAME: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_CRON_ENV_VALUE_CONTROL: Final = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")
_BASE64: Final = re.compile(r"^[A-Za-z0-9+/]*={0,2}$")
_EXPECTED_DIGEST: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
_CRON_FIELD_BOUNDS: Final[dict[str, tuple[int, int]]] = {
    "minute": (0, 59),
    "hour": (0, 23),
    "day_of_month": (1, 31),
    "month": (1, 12),
    "day_of_week": (0, 7),
}
CRON_FIELDS: Final = tuple(_CRON_FIELD_BOUNDS)
_MAX_CRON_ENV_ENTRIES = 16
_MAX_CRON_ENV_VALUE = 1_024
_MAX_CRON_ENV_TOTAL = 8_192
_MAX_CRON_FIELD_LENGTH = 100
_MAX_CRON_FIELD_ELEMENTS = 24
_PROGRAM_EXECUTABLES: Final = frozenset(
    {
        "cat",
        "df",
        "du",
        "echo",
        "free",
        "grep",
        "ip",
        "journalctl",
        "ls",
        "ps",
        "printf",
        "sort",
        "ss",
        "systemctl",
        "tail",
    }
)

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
    if "/" in executable or executable not in _PROGRAM_EXECUTABLES:
        raise ValidationError("executable is not permitted by the typed program policy")
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


def validate_content_b64(content_b64: object, max_size: int = MAX_WRITE_SIZE) -> str:
    """Validate base64-encoded file content with an absolute decoded-size ceiling."""
    if not isinstance(content_b64, str):
        raise ValidationError("content_b64 must be a string")
    if len(content_b64) > max_size * 2 + 8:
        raise ValidationError("content_b64 exceeds the encoded size limit")
    if len(content_b64) % 4 != 0 or not _BASE64.fullmatch(content_b64):
        raise ValidationError("content_b64 must be canonical base64 text")
    try:
        decoded = base64.b64decode(content_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValidationError("content_b64 is not valid base64") from exc
    if len(decoded) > max_size:
        raise ValidationError(f"decoded content too large: {len(decoded)} bytes (max {max_size})")
    return content_b64


def validate_expected_digest(expected_digest: object) -> str:
    if not isinstance(expected_digest, str) or not _EXPECTED_DIGEST.fullmatch(expected_digest):
        raise ValidationError('expected_digest must match "sha256:" followed by 64 hex digits')
    return expected_digest


def validate_cron_profile_id(profile_id: object) -> str:
    if not isinstance(profile_id, str) or not _CRON_PROFILE_ID.fullmatch(profile_id):
        raise ValidationError("profile_id must match [a-z0-9][a-z0-9_-]{0,63}")
    return profile_id


def validate_cron_field(value: object, field: str) -> str:
    bounds = _CRON_FIELD_BOUNDS.get(field)
    if bounds is None:
        raise ValidationError("unknown cron schedule field")
    low, high = bounds
    if not isinstance(value, str) or not value or len(value) > _MAX_CRON_FIELD_LENGTH:
        raise ValidationError(f"{field} must be a bounded cron expression string")
    elements = value.split(",")
    if len(elements) > _MAX_CRON_FIELD_ELEMENTS:
        raise ValidationError(f"{field} contains too many list elements")
    for element in elements:
        body, slash, step_text = element.partition("/")
        if slash:
            if not step_text.isdigit() or not 1 <= int(step_text) <= high:
                raise ValidationError(f"{field} has an out-of-range step value")
        if body == "*":
            continue
        first, dash, last = body.partition("-")
        if not first.isdigit():
            raise ValidationError(f"{field} elements must be numeric ranges or steps")
        start = int(first)
        if dash:
            if not last.isdigit():
                raise ValidationError(f"{field} ranges must use numeric bounds")
            end = int(last)
        else:
            end = high if slash else start
        if not low <= start <= high or not low <= end <= high or start > end:
            raise ValidationError(f"{field} values must be between {low} and {high}")
    return value


def validate_cron_schedule(schedule: object) -> dict[str, str]:
    if not isinstance(schedule, dict) or set(schedule) != set(CRON_FIELDS):
        raise ValidationError(
            "schedule must provide exactly minute, hour, day_of_month, month, day_of_week"
        )
    return {field: validate_cron_field(schedule[field], field) for field in CRON_FIELDS}


def validate_cron_environment(environment: object) -> dict[str, str]:
    if environment is None:
        return {}
    if not isinstance(environment, dict) or len(environment) > _MAX_CRON_ENV_ENTRIES:
        raise ValidationError(
            f"environment must be an object of at most {_MAX_CRON_ENV_ENTRIES} entries"
        )
    result: dict[str, str] = {}
    total = 0
    for key, value in environment.items():
        if not isinstance(key, str) or not _CRON_ENV_NAME.fullmatch(key):
            raise ValidationError("environment keys must be valid identifier names")
        if not isinstance(value, str) or len(value) > _MAX_CRON_ENV_VALUE:
            raise ValidationError("environment values must be bounded strings")
        if _CRON_ENV_VALUE_CONTROL.search(value):
            raise ValidationError("environment values must not contain control characters")
        total += len(key.encode("utf-8")) + len(value.encode("utf-8"))
        if total > _MAX_CRON_ENV_TOTAL:
            raise ValidationError("environment exceeds the total size limit")
        result[key] = value
    return result


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


_COMPOSE_NAME: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_DESIRED_IMAGE: Final = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./:@-]{0,253}$")
_PLAN_RECEIPT: Final = re.compile(r"^plan:v1:sha256:[0-9a-f]{64}$")
_MAX_COMPOSE_FILES = 8


def validate_compose_name(value: object) -> str:
    if not isinstance(value, str) or not _COMPOSE_NAME.fullmatch(value):
        raise ValidationError("compose project and service names must be bounded identifiers")
    return value


def validate_desired_image(value: object) -> str:
    if not isinstance(value, str) or not _DESIRED_IMAGE.fullmatch(value):
        raise ValidationError("desired_image must be a bounded image reference")
    return value


def validate_plan_receipt(value: object) -> str:
    if not isinstance(value, str) or not _PLAN_RECEIPT.fullmatch(value):
        raise ValidationError('plan_receipt must match "plan:v1:sha256:" followed by 64 hex digits')
    return value


def validate_compose_files(value: object) -> list[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= _MAX_COMPOSE_FILES:
        raise ValidationError(f"compose_files must be a list of 1 to {_MAX_COMPOSE_FILES} paths")
    files = [validate_path(item) for item in value]
    if len(set(files)) != len(files):
        raise ValidationError("compose_files must not contain duplicates")
    return files
