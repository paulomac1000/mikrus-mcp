"""Deterministic application validation used before network or privileged I/O."""

from __future__ import annotations

import base64
import binascii
import ipaddress
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


class ProgramPolicyError(ValidationError):
    """Typed program invocation violates the per-executable admission policy.

    The policy_code is prefixed to the rendered message so the public error
    envelope remains machine-readable without expanding the error taxonomy.
    """

    def __init__(self, policy_code: str, message: str) -> None:
        super().__init__(f"{policy_code}: {message}")
        self.policy_code = policy_code


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
_ASCII_DECIMAL: Final = re.compile(r"[0-9]+")


def _ascii_decimal(value: str) -> bool:
    return _ASCII_DECIMAL.fullmatch(value) is not None


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
# Issue #27 intentionally widens typed-program admission: bounded literal
# strings replace the argv charset whitelist, and per-executable subcommand
# policies below gate the newly admitted executables.
_PROGRAM_EXECUTABLES: Final = frozenset(
    {
        "cat",
        "grep",
        "ip",
        "journalctl",
        "ss",
        "sort",
        "tail",
        "docker",
        "curl",
        "systemctl",
    }
)
_MAX_PROGRAM_ARGV_ENTRIES = 128
_MAX_PROGRAM_ARGV_ELEMENT = 4_096
_MAX_PROGRAM_ARGV_TOTAL = 100_000

_DOCKER_READ_SUBCOMMANDS: Final = frozenset(
    {"inspect", "ps", "images", "logs", "version", "info", "stats", "top"}
)
_DOCKER_READ_SUBCOMMAND_PHRASES: Final = frozenset(
    {"network inspect", "volume ls", "volume inspect"}
)
_DOCKER_GLOBAL_FLAGS: Final = frozenset({"--debug", "-D", "--help", "--version", "-v"})

_CURL_NULL_OUTPUT: Final = "/dev/null"
# Diagnostic curl admission is an allowlist: anything not listed here is
# rejected before dispatch. This is the fail-closed answer to config-file
# injection (-K/--config/- reads caller-controlled stdin), implicit .curlrc
# activation, and indirect file I/O reported in security review.
_CURL_ALLOWED_FLAGS_WITH_VALUE: Final = frozenset(
    {
        "-o",  # value restricted to /dev/null
        "-w",  # value restricted: format string, never @file
        "-H",  # request header; method-safe
        "-m",
        "--max-time",
        "--connect-timeout",
        "--url",  # destination policy still applies
        "-X",  # value restricted to GET/HEAD
        "--request",
        "-A",
        "--user-agent",
    }
)
_CURL_ALLOWED_FLAG_VALUE_PREFIXES: Final = ("--write-out=", "--header=", "--url=")
_CURL_ALLOWED_FLAGS_NO_VALUE: Final = frozenset(
    {
        "-q",
        "--disable",  # must be first; disables implicit .curlrc
        "-s",
        "--silent",
        "-S",
        "--show-error",
        "-I",
        "--head",
        "-v",
        "--verbose",
        "-i",
        "--include",
        "--compressed",
    }
)
_CURL_METHODS_ALLOWED: Final = frozenset({"GET", "HEAD"})
_CURL_DISABLED_CONFIG_FLAGS: Final = frozenset({"-q", "--disable"})
_CURL_SCHEMES_ALLOWED: Final = frozenset({"http", "https"})
_CURL_LOCAL_HOST_SUFFIXES: Final = (
    ".localhost",
    ".local",
    ".internal",
    ".home.arpa",
)
_CURL_LOCAL_HOST_NAMES: Final = frozenset({"localhost", "metadata"})


def _curl_host_is_private_literal(host: str) -> bool:
    """True for IP literals in loopback, private, link-local, CGNAT,
    unspecified, or v4-mapped private space (security: SSRF classes)."""
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    host = host.split("%", 1)[0]
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return not address.is_global


def _curl_url_violation(url: str, destinations: frozenset[str]) -> str | None:
    """Return a policy reason when a curl destination is not admitted."""
    scheme, separator, remainder = url.lower().partition("://")
    if separator != "://" or scheme not in _CURL_SCHEMES_ALLOWED:
        return (
            "destination scheme is not permitted; only explicit "
            "http:// or https:// URLs are admitted"
        )
    authority = remainder.split("/", 1)[0].split("?", 1)[0]
    if "@" in authority:
        return "destination user-info (@) is not permitted"
    if authority.startswith("["):
        host = authority[1 : authority.index("]")] if "]" in authority else authority[1:]
    else:
        host = authority.rsplit(":", 1)[0]
    if host in _CURL_LOCAL_HOST_NAMES or host.endswith(_CURL_LOCAL_HOST_SUFFIXES):
        return "local destination hosts are not permitted by the diagnostic curl policy"
    if _curl_host_is_private_literal(host):
        return (
            "loopback, private, link-local, or metadata destinations are not "
            "permitted by the diagnostic curl policy"
        )
    if destinations:
        normalized = host.lower()
        if not any(
            normalized == entry or normalized.endswith("." + entry) for entry in destinations
        ):
            return "destination is not on the configured curl destination allowlist"
    return None


def _curl_constrain_value(flag: str, value: str | None) -> None:
    """Security constraints for allowlisted curl flags that carry a value."""
    if flag in {"-X", "--request"} and (value or "").upper() not in _CURL_METHODS_ALLOWED:
        raise ProgramPolicyError(
            "PROGRAM_ARGUMENT_NOT_PERMITTED",
            f"curl method '{value or ''}' is not permitted; the diagnostic "
            "curl policy admits only GET and HEAD",
        )
    if flag in {"-w", "--write-out"} and value is not None and value.startswith("@"):
        raise ProgramPolicyError(
            "PROGRAM_ARGUMENT_NOT_PERMITTED",
            "curl write-out format from a file is not permitted by the diagnostic curl policy",
        )
    if flag == "-o" and value != _CURL_NULL_OUTPUT:
        raise ProgramPolicyError(
            "PROGRAM_ARGUMENT_NOT_PERMITTED",
            f"curl output target '{value}' is not permitted; only "
            f"'{_CURL_NULL_OUTPUT}' is admitted by the diagnostic curl policy",
        )


def _enforce_curl_program_policy(
    argv: list[str], destinations: frozenset[str] = frozenset()
) -> None:
    if not argv or argv[0] not in _CURL_DISABLED_CONFIG_FLAGS:
        raise ProgramPolicyError(
            "PROGRAM_ARGUMENT_NOT_PERMITTED",
            "curl must start with '-q' or '--disable' so the implicit .curlrc "
            "configuration file cannot alter the admitted invocation",
        )
    index = 1
    while index < len(argv):
        token = argv[index]
        if token.startswith("-"):
            if token in _CURL_ALLOWED_FLAGS_NO_VALUE:
                index += 1
                continue
            combined: str | None = None
            if len(token) > 2 and not token.startswith("--"):
                chars = token[1:]
                if all(f"-{c}" in _CURL_ALLOWED_FLAGS_NO_VALUE for c in chars):
                    index += 1
                    continue
                if (
                    all(f"-{c}" in _CURL_ALLOWED_FLAGS_NO_VALUE for c in chars[:-1])
                    and f"-{chars[-1]}" in _CURL_ALLOWED_FLAGS_WITH_VALUE
                ):
                    combined = f"-{chars[-1]}"
            if combined is not None:
                value, index = _curl_option_value(argv, index)
                _curl_constrain_value(combined, value)
                continue
            if token in _CURL_ALLOWED_FLAGS_WITH_VALUE or token.startswith(
                _CURL_ALLOWED_FLAG_VALUE_PREFIXES
            ):
                value, index = _curl_option_value(argv, index)
                flag = token.partition("=")[0]
                _curl_constrain_value(flag, value)
                continue
            raise ProgramPolicyError(
                "PROGRAM_ARGUMENT_NOT_PERMITTED",
                f"curl option '{token}' is not part of the diagnostic option "
                "allowlist; request-body, upload, config-file, proxy, unix-socket, "
                "trace, and file I/O options are rejected before dispatch",
            )
        reason = _curl_url_violation(token, destinations)
        if reason is not None:
            raise ProgramPolicyError("PROGRAM_ARGUMENT_NOT_PERMITTED", reason)
        index += 1


_SYSTEMCTL_READ_SUBCOMMANDS: Final = frozenset(
    {
        "status",
        "list-units",
        "list-unit-files",
        "is-active",
        "is-enabled",
        "show",
        "cat",
        "list-timers",
        "is-failed",
    }
)
_SYSTEMCTL_GLOBAL_FLAGS: Final = frozenset(
    {"--no-pager", "-l", "--full", "-a", "--all", "-q", "--quiet", "--no-legend", "--plain"}
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
    if not isinstance(argv, list) or len(argv) > _MAX_PROGRAM_ARGV_ENTRIES:
        raise ValidationError("argv must be a list containing at most 128 strings")
    result: list[str] = []
    total = 0
    for value in argv:
        if (
            not isinstance(value, str)
            or not value
            or len(value) > _MAX_PROGRAM_ARGV_ELEMENT
            or _PROGRAM_CONTROL.search(value)
        ):
            raise ValidationError("argv entries must be bounded typed arguments")
        try:
            total += len(value.encode("utf-8"))
        except UnicodeEncodeError as exc:  # lone surrogates stay in the validation contract
            raise ValidationError("argv entries must be bounded typed arguments") from exc
        if total > _MAX_PROGRAM_ARGV_TOTAL:
            raise ValidationError("argv exceeds the 100000-byte limit")
        result.append(value)
    return result


def _enforce_docker_program_policy(argv: list[str]) -> None:
    index = 0
    while index < len(argv) and argv[index] in _DOCKER_GLOBAL_FLAGS:
        index += 1
    if index >= len(argv):
        raise ProgramPolicyError(
            "PROGRAM_SUBCOMMAND_NOT_PERMITTED",
            "docker requires an admitted read-only subcommand",
        )
    phrase = " ".join(argv[index : index + 2])
    if phrase in _DOCKER_READ_SUBCOMMAND_PHRASES:
        return
    subcommand = argv[index]
    if subcommand in _DOCKER_READ_SUBCOMMANDS:
        return
    raise ProgramPolicyError(
        "PROGRAM_SUBCOMMAND_NOT_PERMITTED",
        f"docker subcommand '{subcommand}' is not permitted by the read-only docker policy",
    )


def _curl_option_value(argv: list[str], index: int) -> tuple[str | None, int]:
    """Return the option value (or None) and the next unconsumed index."""
    token = argv[index]
    if token.startswith("--"):
        if "=" in token:
            return token.partition("=")[2], index + 1
        return (argv[index + 1] if index + 1 < len(argv) else None, index + 2)
    if len(token) > 2:
        return token[2:], index + 1
    return (argv[index + 1] if index + 1 < len(argv) else None, index + 2)


def _enforce_systemctl_program_policy(argv: list[str]) -> None:
    index = 0
    while index < len(argv) and argv[index] in _SYSTEMCTL_GLOBAL_FLAGS:
        index += 1
    if index >= len(argv):
        raise ProgramPolicyError(
            "PROGRAM_SUBCOMMAND_NOT_PERMITTED",
            "systemctl requires an admitted read-only subcommand",
        )
    subcommand = argv[index]
    if subcommand in _SYSTEMCTL_READ_SUBCOMMANDS:
        return
    raise ProgramPolicyError(
        "PROGRAM_SUBCOMMAND_NOT_PERMITTED",
        f"systemctl subcommand '{subcommand}' is not permitted by the read-only "
        "systemctl policy; service mutations use the dedicated "
        "change_service_state capability",
    )


_PROGRAM_POLICIES: Final = {
    "docker": _enforce_docker_program_policy,
    "curl": _enforce_curl_program_policy,
    "systemctl": _enforce_systemctl_program_policy,
}


def validate_program_invocation(
    executable: str,
    argv: object,
    *,
    curl_destinations: frozenset[str] = frozenset(),
) -> list[str]:
    executable = validate_program_executable(executable)
    arguments = validate_program_arguments(argv)
    if executable == "curl":
        _enforce_curl_program_policy(arguments, curl_destinations)
        return arguments
    policy = _PROGRAM_POLICIES.get(executable)
    if policy is not None:
        policy(arguments)
    return arguments


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
            if not _ascii_decimal(step_text) or not 1 <= int(step_text) <= high:
                raise ValidationError(f"{field} has an out-of-range step value")
        if body == "*":
            continue
        first, dash, last = body.partition("-")
        if not _ascii_decimal(first):
            raise ValidationError(f"{field} elements must be numeric ranges or steps")
        start = int(first)
        if dash:
            if not _ascii_decimal(last):
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
