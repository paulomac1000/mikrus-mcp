"""Configuration loader — single or multi-server support.

Supports mikr.us API mode, SSH-only mode, and mixed multi-server mode.
Environment variable aliases allow using MCP_* or MIKRUS_* names interchangeably.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

VALID_SERVER_TYPES = frozenset({"mikrus", "ssh"})
REQUIRED_MIKRUS_KEYS = frozenset({"key", "srv"})
REQUIRED_SSH_KEYS = frozenset({"host"})


def _get_env(*keys: str) -> str | None:
    """Get the first non-empty environment variable from the given keys."""
    for key in keys:
        val = os.getenv(key)
        if val:
            return val
    return None


def _validate_server(name: str, cfg: dict[str, Any]) -> None:
    """Validate a single server configuration entry (mutates in place)."""
    if not isinstance(cfg, dict):
        raise RuntimeError(
            f"Server '{name}': configuration must be an object, got {type(cfg).__name__}"
        )
    stype = cfg.get("type", "mikrus")
    if stype not in VALID_SERVER_TYPES:
        raise RuntimeError(f"Server '{name}': unknown type '{stype}'")
    if stype == "mikrus":
        for k in REQUIRED_MIKRUS_KEYS:
            if k not in cfg or not cfg[k]:
                raise RuntimeError(f"Server '{name}': '{k}' is required and cannot be empty")
        cfg.setdefault("api_url", "https://api.mikr.us")
        cfg["type"] = "mikrus"
    elif stype == "ssh":
        for k in REQUIRED_SSH_KEYS:
            if k not in cfg or not cfg[k]:
                raise RuntimeError(f"Server '{name}': '{k}' is required and cannot be empty")
        cfg.setdefault("port", 22)
        cfg.setdefault("user", "root")
        cfg.setdefault("ssh_key", None)
        cfg.setdefault("password", None)
        cfg.setdefault("sudo_password", None)
        cfg.setdefault("timeout", 30)
        cfg.setdefault("verify_host_key", False)
        cfg.setdefault("known_hosts_file", None)
        cfg.setdefault("ssh_cert", None)
        cfg["type"] = "ssh"
        if cfg.get("ssh_key"):
            key_path = Path(cfg["ssh_key"]).expanduser()
            if not key_path.exists():
                raise RuntimeError(f"Server '{name}': SSH key not found: {key_path}")
            mode = oct(key_path.stat().st_mode)[-3:]
            if mode not in ("600", "400"):
                logger.warning(
                    "Server '%s': SSH key %s has permissions %s (should be 600)",
                    name,
                    key_path,
                    mode,
                )
        if cfg.get("ssh_cert"):
            cert_path = Path(cfg["ssh_cert"]).expanduser()
            if not cert_path.exists():
                raise RuntimeError(f"Server '{name}': SSH certificate not found: {cert_path}")


def load_config() -> dict[str, Any]:
    """Load and validate server configuration.

    Supports three modes:
    1. Legacy: MIKRUS_API_KEY + MIKRUS_SERVER_NAME env vars (single mikrus)
    2. Multi:  MCP_SERVERS / MIKRUS_SERVERS JSON with one or more entries
    3. SSH-only: MCP_SERVERS with only SSH entries (no mikr.us needed)

    Env var priority (first found wins):
    - Servers JSON: MCP_SERVERS → MIKRUS_SERVERS
    - Default:     MCP_DEFAULT_SERVER → MIKRUS_DEFAULT_SERVER
    - API key:     MIKRUS_API_KEY
    - Server name: MIKRUS_SERVER_NAME
    """
    servers_json = _get_env("MCP_SERVERS", "MIKRUS_SERVERS")
    api_key = _get_env("MIKRUS_API_KEY")
    server_name = _get_env("MIKRUS_SERVER_NAME")
    base_url = os.getenv("MIKRUS_API_URL", "https://api.mikr.us")
    default_server = _get_env("MCP_DEFAULT_SERVER", "MIKRUS_DEFAULT_SERVER")

    if servers_json:
        try:
            servers = json.loads(servers_json)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid servers JSON: {exc}") from exc
        if not isinstance(servers, dict):
            raise RuntimeError("Servers JSON must be a JSON object")
        if not servers:
            raise RuntimeError("Servers JSON must contain at least one server")
        for name, cfg in servers.items():
            _validate_server(name, cfg)
        if not default_server:
            default_server = next(iter(servers.keys()))
        if default_server not in servers:
            raise RuntimeError(f"Default server '{default_server}' not in servers JSON")
        logger.info("Loaded %d servers, default: %s", len(servers), default_server)
        return {"servers": servers, "default": default_server}

    if api_key and server_name:
        logger.info("Legacy single-server mode: %s", server_name)
        default_server = default_server or server_name
        return {
            "servers": {
                server_name: {
                    "type": "mikrus",
                    "key": api_key,
                    "srv": server_name,
                    "api_url": base_url,
                }
            },
            "default": default_server,
        }

    raise RuntimeError(
        "Set either MIKRUS_API_KEY+MIKRUS_SERVER_NAME or MCP_SERVERS / MIKRUS_SERVERS JSON"
    )
