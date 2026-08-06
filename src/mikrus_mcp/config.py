"""Typed immutable configuration loaded before dependency construction."""

from __future__ import annotations

import ipaddress
import json
import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal, cast

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


def _integer(
    env: Mapping[str, str], name: str, default: int, minimum: int, maximum: int
) -> int:
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
    principal: str = "local-stdio-user"
    allowed_scopes: frozenset[str] = frozenset({"tool:*", "target:*"})
    write_enabled: bool = False
    command_execution_enabled: bool = False
    default_deadline_ms: int = 10_000
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
        if not 1_024 <= self.max_request_body_bytes <= 16_777_216:
            raise ValueError,"request body limit must be between 1024 and 16777216 bytes")
        if not 1_024 <= self.max_result_bytes <= 16_777_216:
            raise ValueError("result limit must be between 1024 and 16777216 bytes")
        for target in self.targets.values():
            if target.type == "ssh" and not target.verify_host_key and not self.allow_insecure_ssh:
                raise ValueError(
                    f"target '{target.name}' disables SSH host verification without "
                    "MCP_ALLOW_INSECURE_SSH=1"
                )
        return self


def _target(name: str, raw: object) -> TargetConfig:
    if not isinstance(raw, dict):
        raise ValueError(f"target '{name}' must be an object")
    target_type = raw.get("type", "mikrus")
    if target_type == "mikrus":
        api_key = raw.get("key")
        server_id = raw.get("srv")
        api_url = raw.get("api_url", "https://api.mikr.us")
        if not isinstance(api_key, str) or not api_key:
            raise ValueError(f"target '{name}' requires key")
        if not isinstance(server_id, str) or not server_id:
            raise ValueError(f"target '{name}' requires srv")
        if not isinstance(api_url, str) or not api_url.startswith("https://"):
            raise ValueError(f"target '{name}' api_url must use https")
        return TargetConfig(
            name=name,
            type="mikrus",
            api_url=api_url.rstrip("/"),
            api_key=api_key,
            server_id=server_id,
        )
    if target_type != "ssh":
        raise ValueError(f"target '{name}' has unknown type '{target_type}'")
    host = raw.get("host")
    if not isinstance(host, str) or not host:
        raise ValueError(f"target '{name}' requires host")
    try:
        port = int(raw.get("port", 22))
        timeout = int(raw.get("timeout", 30))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"target '{name}' port and timeout must be integers") from exc
    if not 1 <= port <= 65_535:
        raise ValueError(f"target '{name}' port must be between 1 and 65535")
    if not 1 <= timeout <= 300:
        raise ValueError(f"target '{name}' timeout must be between 1 and 300 seconds")
    verify_host_key = raw.get("verify_host_key", True)
    if type(verify_host_key) is not bool:
        raise ValueError(f"target '{name}' verify_host_key must be boolean")
    return TargetConfig(
        name=name,
        type="ssh",
        host=host,
        port=port,
        user=str(raw.get("user", "root")),
        password=raw.get("password") if isinstance(raw.get("password"), str) else None,
        sudo_password=(
            raw.get("sudo_password") if isinstance(raw.get("sudo_password"), str) else None
        ),
        ssh_key=_optional_regular_file(
            raw.get("ssh_key"),
            name=f"target '{name}' ssh_key",
            secret=True,
        ),
        ssh_cert=_optional_regular_file(raw.get("ssh_cert"), name=f"target '{name}' ssh_cert"),
        known_hosts_file=_optional_regular_file(
            raw.get("known_hosts_file"), name=f"target '{name}' known_hosts_file"
        ),
        connect_timeout_seconds=timeout,
        verify_host_key=verify_host_key,
    )


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Load, validate, and freeze one process settings snapshot."""
    env = os.environ if env is None else env
    raw_targets = env.get("MCP_SERVERS") or env.get("MIKRUS_SERVERS")
    parsed: dict[str, TargetConfig]
    if raw_targets:
        try:
            target_data = json.loads(raw_targets)
        except json.JSONDecodeError as exc:
            raise ValueError(f"MCP_SERVERS is invalid JSON: {exc.msg}") from exc
        if not isinstance(target_data, dict) or not target_data:
            raise ValueError("MCP_SERVERS must be a non-empty object")
        parsed = {_name: _target(_name, value) for _name, value in target_data.items()}
    else:
        api_key = env.get("MIKRUS_API_KEY")
        server_id = env.get("MIKRUS_SERVER_NAME")
        if not api_key or not server_id:
            raise ValueError(
                "set MCP_SERVERS or both MIKRUS_API_KEY and MIKRUS_SERVER_NAME"
            )
        parsed = {
            server_id: _target(
                server_id,
                {
                    "type": "mikrus",
                    "key": api_key,
                    "srv": server_id,
                    "api_url": env.get("MIKRUS_API_URL", "https://api.mikr.us"),
                },
            )
        }

    transport = env.get("MCP_TRANSPORT", "stdio").strip().casefold()
    principal_default = "local-http-user" if transport == "streamable-http" else "local-stdio-user"
    scope_raw = env.get("MCP_ALLOWED_SCOPES", "tool:*,target:*")
    scopes = frozenset(value.strip() for value in scope_raw.split(",") if value.strip())
    default_target = (
        env.get("MCP_DEFAULT_SERVER")
        or env.get("MIKRUS_DEFAULT_SERVER")
        or next(iter(parsed))
    )
    settings = Settings(
        targets=MappingProxyType(parsed),
        default_target=default_target,
        transport=cast(Transport, transport),
        host=env.get("MCP_HOST", "127.0.0.1").strip(),
        port=_integer(env, "MCP_PORT", 8000, 1, 65_535),
        principal=env.get("MCP_PRINCIPAL", principal_default).strip(),
        allowed_scopes=scopes,
        write_enabled=_boolean(env, "MCP_WRITE_ENABLED", False),
        command_execution_enabled=_boolean(env, "MCP_COMMAND_EXECUTION_ENABLED", False),
        default_deadline_ms=_integer(env, "MCP_DEFAULT_DEADLINE_MS", 10_000, 100, 120_000),
        max_request_body_bytes=_integer(
            env, "MCP_MAX_REQUEST_BODY_BYTES", 1_048_576, 1_024, 16_777_216
        ),
        max_result_bytes=_integer(
            env, "MCP_MAX_RESULT_BYTES", 1_000_000, 1_024, 16_777_216
        ),
        approval_file=_optional_regular_file(
            env.get("MCP_APPROVAL_FILE"), name="MCP_APPROVAL_FILE", secret=True
        ),
        http_bearer_token=_secret_text_file(
            env.get("MCP_HTTP_BEARER_TOKEN_FILE"), name="MCP_HTTP_BEARER_TOKEN_FILE"
        ),
        allow_insecure_ssh=_boolean(env, "MCP_ALLOW_INSECURE_SSH", False),
    )
    return settings.validate()
