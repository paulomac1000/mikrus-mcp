"""Typed immutable configuration loaded before dependency construction."""

from __future__ import annotations

import ipaddress
import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

Transport = Literal["stdio", "streamable-http"]
TargetType = Literal["mikrus", "ssh"]


def _boolean(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None:
        return default
    value = raw.strip().casefold()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def _integer(env: Mapping[str, str], name: str, default: int, minimum: int, maximum: int) -> int:
    raw = env.get(name)
    try:
        value = default if raw is None else int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _optional_regular_file(raw: object, *, name: str, secret: bool = False) -> Path | None:
    if raw in (None, ""):
        return None
    if not isinstance(raw, str):
        raise ValueError(f"{name} must be a path string")
    path = Path(raw).expanduser()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{name} must be an existing regular non-symlink file")
    metadata = path.stat()
    if secret and metadata.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise ValueError(f"{name} must not be accessible to group or other users")
    if secret and hasattr(os, "getuid") and metadata.st_uid != os.getuid():
        raise ValueError(f"{name} must be owned by the current process user")
    return path.resolve()


def _secret_text_file(raw: object, *, name: str) -> str | None:
    path = _optional_regular_file(raw, name=name, secret=True)
    if path is None:
        return None
    if path.stat().st_size > 4_096:
        raise ValueError(f"{name} must not exceed 4096 bytes")
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValueError(f"{name} could not be read") from exc
    if "\n" in value or "\r" in value:
        raise ValueError(f"{name} must contain exactly one token")
    if len(value) < 32:
        raise ValueError(f"{name} must contain at least 32 characters")
    return value


def _default_stdio_principal() -> str:
    if hasattr(os, "geteuid"):
        return f"posix-uid:{os.geteuid()}"
    import getpass

    return f"os-user:{getpass.getuser()}"


def _require_loopback(host: str) -> None:
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError("MCP_HOST must be a literal IPv4 or IPv6 loopback address") from exc
    if not address.is_loopback:
        raise ValueError("Streamable HTTP is restricted to literal loopback addresses")


@dataclass(frozen=True, slots=True)
class TargetConfig:
    name: str
    type: TargetType
    api_url: str | None = None
    api_key: str | None = None
    server_id: str | None = None
    host: str | None = None
    port: int = 22
    user: str = "root"
    password: str | None = None
    sudo_password: str | None = None
    ssh_key: Path | None = None
    ssh_cert: Path | None = None
    known_hosts_file: Path | None = None
    connect_timeout_seconds: int = 30
    verify_host_key: bool = True

    @property
    def stable_identity(self) -> str:
        if self.type == "mikrus":
            return f"mikrus:{self.server_id}"
        return f"ssh:{self.user}@{self.host}:{self.port}"


@dataclass(frozen=True, slots=True)
class Settings:
    targets: Mapping[str, TargetConfig]
    default_target: str
    transport: Transport = "stdio"
    host: str = "127.0.0.1"
    port: int = 8000
    principal: str = field(default_factory=_default_stdio_principal)
    allowed_scopes: frozenset[str] = frozenset({"tool:*", "target:*"})
    write_enabled: bool = False
    default_deadline_ms: int = 120_000
    server_max_deadline_ms: int = 120_000
    max_request_body_bytes: int = 1_048_576
    max_result_bytes: int = 1_000_000
    approval_file: Path | None = None
    http_bearer_token: str | None = None
    allow_insecure_ssh: bool = False

    def validate(self) -> Settings:
        if not self.targets:
            raise ValueError("at least one target must be configured")
        if self.default_target not in self.targets:
            raise ValueError("default target is not configured")
        if self.transport not in {"stdio", "streamable-http"}:
            raise ValueError("transport must be stdio or streamable-http")
        if self.transport == "streamable-http":
            _require_loopback(self.host)
            if not self.http_bearer_token or len(self.http_bearer_token) < 32:
                raise ValueError(
                    "Streamable HTTP requires an owner-only MCP_HTTP_BEARER_TOKEN_FILE "
                    "containing at least 32 characters"
                )
        if not 1 <= self.port <= 65_535:
            raise ValueError("port must be between 1 and 65535")
        if not self.principal:
            raise ValueError("principal must be non-empty")
        if not 100 <= self.default_deadline_ms <= 120_000:
            raise ValueError("default deadline must be between 100 and 120000 ms")
        if not 100 <= self.server_max_deadline_ms <= 120_000:
            raise ValueError("server maximum deadline must be between 100 and 120000 ms")
        if not 1_024 <= self.max_request_body_bytes <= 16_777_216:
            raise ValueError("request body limit must be between 1024 and 16777216 bytes")
        if not 1_024 <= self.max_result_bytes <= 16_777_216:
            raise ValueError("result limit must be between 1024 and 16777216 bytes")
        for key, target in self.targets.items():
            if key != target.name:
                raise ValueError(
                    f"target mapping key '{key}' does not match target name '{target.name}'"
                )
            if target.type == "ssh" and not target.verify_host_key and not self.allow_insecure_ssh:
                raise ValueError(
                    f"target '{target.name}' disables SSH host verification without "
                    "MCP_ALLOW_INSECURE_SSH=1"
                )
            if target.type == "ssh" and not target.verify_host_key and self.write_enabled:
                raise ValueError(
                    f"target '{target.name}' cannot be used for writes without "
                    "SSH host verification"
                )
        return self
