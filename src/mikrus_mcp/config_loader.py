"""Environment and JSON loader for immutable target settings."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from types import MappingProxyType
from typing import cast

from mikrus_mcp.config_models import (
    Settings,
    TargetConfig,
    Transport,
    _boolean,
    _integer,
    _optional_regular_file,
    _secret_text_file,
)


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
