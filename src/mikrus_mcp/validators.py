"""Input validators for security and data integrity."""

import logging
import os
import re
from typing import Final

logger = logging.getLogger(__name__)

from mikrus_mcp.tools.constants import (  # noqa: E402
    MAX_GREP_HOURS,
    MAX_TAIL_LINES,
    MAX_WRITE_SIZE,
    SERVICE_ACTIONS,
    write_operations_enabled,
)


class ValidationError(ValueError):
    """Raised when input validation fails."""

    pass


class WriteOperationsDisabledError(ValidationError):
    """Raised when a write/destructive tool is invoked while the write guard is off."""

    pass


def check_write_enabled() -> None:
    """Enforce the server-level write guard before any write/destructive I/O.

    Raises WriteOperationsDisabledError when ENABLE_WRITE_OPERATIONS is not set.
    This is a server-level authorization gate (mcp-server-standards.md — Write
    Guard, L2+), distinct from the per-tool ``requires_confirmation`` agent hint.
    MUST be called before any I/O in every write, destructive, or command tool.
    """
    if not write_operations_enabled():
        raise WriteOperationsDisabledError(
            "Write operations are disabled on this MCP server. "
            "Ask the administrator to set ENABLE_WRITE_OPERATIONS=1 to enable "
            "write, destructive, and command-execution tools."
        )


# Shell metacharacters rejected in file paths. Validated parameters are
# interpolated into single-quoted shell commands; these characters could break
# out of the quoting and inject commands, so they are denied by default.
SHELL_UNSAFE_CHARS: Final = frozenset("'\"`$;|&<>(){}[]*?!~\\\n\r\t")


PATH_PATTERN: Final = re.compile(r"^[^\x00-\x1f\x7f]+$")
SERVICE_NAME_PATTERN: Final = re.compile(r"^[a-zA-Z0-9_\-@.]+$")
CONTAINER_NAME_PATTERN: Final = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.\-]*$")
DOMAIN_PATTERN: Final = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)*"
    r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$|^-$"
)
SEARCH_PATTERN: Final = re.compile(r"^[a-zA-Z0-9_\-./:@\s]+$")
USERNAME_PATTERN: Final = re.compile(r"^[a-z_][a-z0-9_-]*$")

WRITE_FORBIDDEN_PATHS: Final = frozenset(
    {
        "/etc/passwd",
        "/etc/shadow",
        "/etc/gshadow",
        "/etc/sudoers",
        "/etc/sudoers.d",
        "/root/.ssh/authorized_keys",
        "/etc/ssh/sshd_config",
        "/boot",
        "/sys",
        "/proc",
    }
)

READ_FORBIDDEN_PATHS: Final = frozenset(
    {
        "/etc/shadow",
        "/etc/gshadow",
        "/root/.ssh/id_rsa",
        "/root/.ssh/id_ed25519",
        "/root/.ssh/id_ecdsa",
    }
)

WRITE_ALLOWED_PREFIXES: Final = (
    "/home",
    "/var/www",
    "/opt",
    "/tmp",  # nosec B108
    "/srv",
    "/var/log",
)

DANGEROUS_PATTERNS: Final = [
    re.compile(r"rm\s+(-[rfRF]+\s+)?/\s*$"),
    re.compile(r"mkfs\."),
    re.compile(r"dd\s+if="),
    re.compile(r":\(\)\s*\{"),
    re.compile(r">\s*/dev/sd"),
    re.compile(r"chmod\s+777\s+/"),
]


def validate_path(path: str, *, for_write: bool = False) -> str:
    """Validate and normalize a file path."""
    if not path:
        raise ValidationError("Path cannot be empty")
    if not isinstance(path, str):
        raise ValidationError(f"Path must be string, got {type(path)}")
    if not PATH_PATTERN.match(path):
        raise ValidationError(f"Path contains invalid characters: {path}")
    if not path.startswith("/"):
        raise ValidationError(f"Path must be absolute: {path}")

    if ".." in path.split(os.sep):
        raise ValidationError(f"Path traversal detected: {path}")

    normalized = os.path.normpath(path)

    forbidden = WRITE_FORBIDDEN_PATHS if for_write else READ_FORBIDDEN_PATHS
    for fp in forbidden:
        if normalized.startswith(fp):
            raise ValidationError(f"Access to {fp} is forbidden")

    if for_write:
        if not any(normalized.startswith(prefix) for prefix in WRITE_ALLOWED_PREFIXES):
            logger.warning(
                "Writing to %s — outside typical application directories",
                normalized,
            )
    return normalized


def validate_port(port: str | int) -> int:
    """Validate port number."""
    try:
        port_num = int(port)
    except (ValueError, TypeError) as exc:
        raise ValidationError(f"Port must be a number, got: {port}") from exc
    if not 1 <= port_num <= 65535:
        raise ValidationError(f"Port must be 1-65535, got: {port_num}")
    return port_num


def validate_service_name(name: str) -> str:
    """Validate systemd service name."""
    if not name:
        raise ValidationError("Service name cannot be empty")
    if not SERVICE_NAME_PATTERN.match(name):
        raise ValidationError(f"Invalid service name: {name}")
    if len(name) > 255:
        raise ValidationError(f"Service name too long: {name}")
    return name


def validate_service_action(action: str) -> str:
    """Validate systemd service action."""
    if action not in SERVICE_ACTIONS:
        raise ValidationError(f"Invalid action: {action}. Allowed: {sorted(SERVICE_ACTIONS)}")
    return action


def validate_container_name(name: str) -> str:
    """Validate Docker container name."""
    if not name:
        raise ValidationError("Container name cannot be empty")
    if not CONTAINER_NAME_PATTERN.match(name):
        raise ValidationError(f"Invalid container name: {name}")
    return name


def validate_domain(domain: str) -> str:
    """Validate domain name or '-' for auto."""
    if domain == "-":
        return domain
    if not DOMAIN_PATTERN.match(domain):
        raise ValidationError(f"Invalid domain format: {domain}")
    if len(domain) > 253:
        raise ValidationError(f"Domain too long (max 253 chars): {domain}")
    return domain


def validate_search_pattern(pattern: str) -> str:
    """Validate search/grep pattern."""
    if not pattern:
        raise ValidationError("Search pattern cannot be empty")
    if not SEARCH_PATTERN.match(pattern):
        raise ValidationError(f"Invalid search pattern: {pattern}")
    if len(pattern) > 1000:
        raise ValidationError("Search pattern too long")
    return pattern


def validate_username(username: str) -> str:
    """Validate Unix username."""
    if not username:
        raise ValidationError("Username cannot be empty")
    if not USERNAME_PATTERN.match(username):
        raise ValidationError(f"Invalid username: {username}")
    if len(username) > 32:
        raise ValidationError("Username too long")
    return username


def validate_content_size(content: str, max_size: int = MAX_WRITE_SIZE) -> None:
    """Validate content size for file writes."""
    size = len(content.encode("utf-8"))
    if size > max_size:
        raise ValidationError(f"Content too large: {size} bytes (max {max_size})")


def check_dangerous_command(cmd: str) -> None:
    """Check if command contains dangerous patterns."""
    for pattern in DANGEROUS_PATTERNS:
        if pattern.search(cmd):
            raise ValidationError("Dangerous command pattern detected. This command is blocked.")


def validate_command(cmd: str) -> str:
    """Reject commands containing shell metacharacters (defense-in-depth).

    Must be called BEFORE check_dangerous_command() so the denylist runs
    first (mcp-server-standards.md — Command Execution Allowlist, L2+).
    The returned command string is the validated input.
    """
    if not cmd or not isinstance(cmd, str):
        raise ValidationError("Command cannot be empty")
    unsafe = [c for c in cmd if c in SHELL_UNSAFE_CHARS]
    if unsafe:
        raise ValidationError(
            f"Command contains unsafe characters: {unsafe}. "
            "Use a simple command without shell metacharacters."
        )
    return cmd


def validate_lines_param(lines: int | str, max_lines: int = MAX_TAIL_LINES) -> int:
    """Validate and clamp 'lines' parameter."""
    try:
        lines_int = int(lines)
    except (ValueError, TypeError):
        lines_int = 50
    return max(1, min(lines_int, max_lines))


def validate_hours_param(hours: int | str, max_hours: int = MAX_GREP_HOURS) -> int:
    """Validate and clamp 'hours' parameter."""
    try:
        hours_int = int(hours)
    except (ValueError, TypeError):
        hours_int = 1
    return max(1, min(hours_int, max_hours))
