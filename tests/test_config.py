"""Tests for mikrus_mcp configuration loader."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from mikrus_mcp.config import _get_env, _validate_server, load_config

# ========== _get_env tests ==========


def test_get_env_first_key() -> None:
    with patch.dict(os.environ, {"A": "1", "B": "2"}, clear=False):
        assert _get_env("A", "B") == "1"


def test_get_env_fallback() -> None:
    with patch.dict(os.environ, {"B": "2"}, clear=False):
        assert _get_env("A", "B") == "2"


def test_get_env_empty_skipped() -> None:
    with patch.dict(os.environ, {"A": "", "B": "2"}, clear=False):
        assert _get_env("A", "B") == "2"


def test_get_env_none() -> None:
    with patch.dict(os.environ, {"A": "", "B": ""}, clear=False):
        assert _get_env("A", "B") is None


# ========== _validate_server tests ==========


def test_validate_mikrus_server() -> None:
    cfg = {"type": "mikrus", "key": "k", "srv": "s1"}
    _validate_server("srv1", cfg)
    assert cfg["type"] == "mikrus"
    assert cfg["api_url"] == "https://api.mikr.us"


def test_validate_mikrus_missing_key() -> None:
    cfg = {"type": "mikrus", "srv": "s1"}
    with pytest.raises(RuntimeError, match="'key' is required"):
        _validate_server("srv1", cfg)


def test_validate_mikrus_empty_key() -> None:
    cfg = {"type": "mikrus", "key": "", "srv": "s1"}
    with pytest.raises(RuntimeError, match="'key' is required"):
        _validate_server("srv1", cfg)


def test_validate_mikrus_missing_srv() -> None:
    cfg = {"type": "mikrus", "key": "k"}
    with pytest.raises(RuntimeError, match="'srv' is required"):
        _validate_server("srv1", cfg)


def test_validate_mikrus_not_dict() -> None:
    with pytest.raises(RuntimeError, match="must be an object"):
        _validate_server("srv1", "not-a-dict")


def test_validate_ssh_server_defaults() -> None:
    cfg = {"type": "ssh", "host": "h1"}
    _validate_server("srv1", cfg)
    assert cfg["type"] == "ssh"
    assert cfg["port"] == 22
    assert cfg["user"] == "root"
    assert cfg["ssh_key"] is None
    assert cfg["password"] is None
    assert cfg["sudo_password"] is None
    assert cfg["timeout"] == 30
    assert cfg["verify_host_key"] is False
    assert cfg["known_hosts_file"] is None
    assert cfg["ssh_cert"] is None


def test_validate_ssh_missing_host() -> None:
    cfg = {"type": "ssh"}
    with pytest.raises(RuntimeError, match="'host' is required"):
        _validate_server("srv1", cfg)


def test_validate_ssh_empty_host() -> None:
    cfg = {"type": "ssh", "host": ""}
    with pytest.raises(RuntimeError, match="'host' is required"):
        _validate_server("srv1", cfg)


def test_validate_unknown_type() -> None:
    cfg = {"type": "ftp"}
    with pytest.raises(RuntimeError, match="unknown type 'ftp'"):
        _validate_server("srv1", cfg)


def test_validate_ssh_key_missing() -> None:
    cfg = {"type": "ssh", "host": "h1", "ssh_key": "/nonexistent/key"}
    with pytest.raises(RuntimeError, match="SSH key not found"):
        _validate_server("srv1", cfg)


def test_validate_ssh_key_bad_permissions(caplog: pytest.LogCaptureFixture) -> None:
    cfg = {"type": "ssh", "host": "h1", "ssh_key": "/tmp/test_key"}
    fake_stat = os.stat_result((0o100644, 0, 0, 0, 0, 0, 0, 0, 0, 0))
    with patch.object(Path, "exists", return_value=True):
        with patch.object(Path, "stat", return_value=fake_stat):
            _validate_server("srv1", cfg)
    assert "should be 600" in caplog.text


def test_validate_ssh_cert_missing() -> None:
    cfg = {"type": "ssh", "host": "h1", "ssh_cert": "/nonexistent/cert"}
    with pytest.raises(RuntimeError, match="SSH certificate not found"):
        _validate_server("srv1", cfg)


# ========== load_config tests ==========


def test_load_config_legacy_mode() -> None:
    env = {
        "MIKRUS_API_KEY": "key123",
        "MIKRUS_SERVER_NAME": "srv123",
        "MIKRUS_API_URL": "https://custom.api",
    }
    with patch.dict(os.environ, env, clear=True):
        cfg = load_config()

    assert cfg["default"] == "srv123"
    assert cfg["servers"]["srv123"]["type"] == "mikrus"
    assert cfg["servers"]["srv123"]["key"] == "key123"
    assert cfg["servers"]["srv123"]["api_url"] == "https://custom.api"


def test_load_config_legacy_with_default_override() -> None:
    env = {
        "MIKRUS_API_KEY": "key123",
        "MIKRUS_SERVER_NAME": "srv123",
        "MCP_DEFAULT_SERVER": "srv123",
    }
    with patch.dict(os.environ, env, clear=True):
        cfg = load_config()

    assert cfg["default"] == "srv123"


def test_load_config_multi_server_json() -> None:
    servers = {
        "alpha": {"type": "mikrus", "key": "k1", "srv": "alpha"},
        "beta": {"type": "ssh", "host": "beta.host"},
    }
    env = {"MCP_SERVERS": json.dumps(servers)}
    with patch.dict(os.environ, env, clear=True):
        cfg = load_config()

    assert cfg["default"] == "alpha"
    assert len(cfg["servers"]) == 2
    assert cfg["servers"]["alpha"]["type"] == "mikrus"
    assert cfg["servers"]["beta"]["type"] == "ssh"
    assert cfg["servers"]["beta"]["port"] == 22


def test_load_config_multi_server_with_default() -> None:
    servers = {
        "alpha": {"type": "mikrus", "key": "k1", "srv": "alpha"},
        "beta": {"type": "ssh", "host": "beta.host"},
    }
    env = {
        "MIKRUS_SERVERS": json.dumps(servers),
        "MIKRUS_DEFAULT_SERVER": "beta",
    }
    with patch.dict(os.environ, env, clear=True):
        cfg = load_config()

    assert cfg["default"] == "beta"


def test_load_config_ssh_only() -> None:
    servers = {
        "prod": {"type": "ssh", "host": "prod.example.com", "user": "admin"},
    }
    env = {"MCP_SERVERS": json.dumps(servers)}
    with patch.dict(os.environ, env, clear=True):
        cfg = load_config()

    assert cfg["default"] == "prod"
    assert cfg["servers"]["prod"]["type"] == "ssh"


def test_load_config_invalid_json() -> None:
    env = {"MCP_SERVERS": "not-json"}
    with patch.dict(os.environ, env, clear=True):
        with pytest.raises(RuntimeError, match="Invalid servers JSON"):
            load_config()


def test_load_config_json_not_object() -> None:
    env = {"MCP_SERVERS": "[1, 2, 3]"}
    with patch.dict(os.environ, env, clear=True):
        with pytest.raises(RuntimeError, match="must be a JSON object"):
            load_config()


def test_load_config_empty_json() -> None:
    env = {"MCP_SERVERS": "{}"}
    with patch.dict(os.environ, env, clear=True):
        with pytest.raises(RuntimeError, match="at least one server"):
            load_config()


def test_load_config_default_not_found() -> None:
    servers = {"alpha": {"type": "mikrus", "key": "k", "srv": "alpha"}}
    env = {
        "MCP_SERVERS": json.dumps(servers),
        "MCP_DEFAULT_SERVER": "missing",
    }
    with patch.dict(os.environ, env, clear=True):
        with pytest.raises(RuntimeError, match="Default server 'missing' not in servers JSON"):
            load_config()


def test_load_config_missing_all() -> None:
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(RuntimeError, match="Set either MIKRUS_API_KEY"):
            load_config()


def test_load_config_mcp_aliases_priority() -> None:
    servers_mcp = {"mcp_srv": {"type": "ssh", "host": "mcp.host"}}
    servers_legacy = {"legacy_srv": {"type": "ssh", "host": "legacy.host"}}
    env = {
        "MCP_SERVERS": json.dumps(servers_mcp),
        "MIKRUS_SERVERS": json.dumps(servers_legacy),
    }
    with patch.dict(os.environ, env, clear=True):
        cfg = load_config()

    assert "mcp_srv" in cfg["servers"]
    assert "legacy_srv" not in cfg["servers"]
