from __future__ import annotations

import json
from pathlib import Path

import pytest

from mikrus_mcp.config import Settings, TargetConfig, load_settings


def test_single_mikrus_configuration_is_frozen() -> None:
    settings = load_settings({"MIKRUS_API_KEY": "secret", "MIKRUS_SERVER_NAME": "srv1"})
    assert settings.default_target == "srv1"
    assert settings.targets["srv1"].stable_identity == "mikrus:srv1"
    with pytest.raises(TypeError):
        settings.targets["other"] = settings.targets["srv1"]  # type: ignore[index]


def test_multi_target_default_is_explicit() -> None:
    raw = {
        "api": {"type": "mikrus", "key": "k", "srv": "srv"},
        "ssh": {"type": "ssh", "host": "127.0.0.1"},
    }
    settings = load_settings(
        {"MCP_SERVERS": json.dumps(raw), "MCP_DEFAULT_SERVER": "ssh"}
    )
    assert settings.default_target == "ssh"
    assert settings.targets["ssh"].verify_host_key is True


def test_unknown_default_is_rejected() -> None:
    with pytest.raises(ValueError, match="default target"):
        load_settings(
            {
                "MIKRUS_API_KEY": "k",
                "MIKRUS_SERVER_NAME": "srv",
                "MCP_DEFAULT_SERVER": "missing",
            }
        )


def test_streamable_http_accepts_only_literal_loopback() -> None:
    target = TargetConfig(
        "srv",
        "mikrus",
        api_url="https://api.mikr.us",
        api_key="k",
        server_id="srv",
    )
    Settings(
        {"srv": target},
        "srv",
        transport="streamable-http",
        host="127.0.0.1",
        http_bearer_token="x" * 32,
    ).validate()
    Settings(
        {"srv": target},
        "srv",
        transport="streamable-http",
        host="::1",
        http_bearer_token="x" * 32,
    ).validate()
    for host in ("localhost", "0.0.0.0", "::", "192.168.1.10"):
        with pytest.raises(ValueError, match="loopback"):
            Settings(
                {"srv": target},
                "srv",
                transport="streamable-http",
                host=host,
                http_bearer_token="x" * 32,
            ).validate()


def test_insecure_ssh_requires_separate_operator_acknowledgement() -> None:
    target = TargetConfig("ssh", "ssh", host="127.0.0.1", verify_host_key=False)
    with pytest.raises(ValueError, match="MCP_ALLOW_INSECURE_SSH"):
        Settings({"ssh": target}, "ssh").validate()
    Settings({"ssh": target}, "ssh", allow_insecure_ssh=True).validate()


def test_secret_files_must_have_private_permissions(tmp_path: Path) -> None:
    key = tmp_path / "id_ed25519"
    key.write_text("test", encoding="utf-8")
    key.chmod(0o644)
    raw = {"ssh": {"type": "ssh", "host": "127.0.0.1", "ssh_key": str(key)}}
    with pytest.raises(ValueError, match="group or other"):
        load_settings({"MCP_SERVERS": json.dumps(raw)})
    key.chmod(0o600)
    settings = load_settings({"MCP_SERVERS": json.dumps(raw)})
    assert settings.targets["ssh"].ssh_key == key.resolve()


def test_scope_and_command_profiles_are_process_configuration() -> None:
    settings = load_settings(
        {
            "MIKRUS_API_KEY": "k",
            "MIKRUS_SERVER_NAME": "srv",
            "MCP_ALLOWED_SCOPES": "tool:get_server_info,target:srv",
            "MCP_COMMAND_EXECUTION_ENABLED": "true",
        }
    )
    assert settings.allowed_scopes == frozenset({"tool:get_server_info", "target:srv"})
    assert settings.command_execution_enabled is True


def test_streamable_http_requires_private_bearer_token_file(tmp_path: Path) -> None:
    token_file = tmp_path / "http-token"
    token_file.write_text("a" * 48, encoding="utf-8")
    token_file.chmod(0o600)
    settings = load_settings(
        {
            "MIKRUS_API_KEY": "k",
            "MIKRUS_SERVER_NAME": "srv",
            "MCP_TRANSPORT": "streamable-http",
            "MCP_HTTP_BEARER_TOKEN_FILE": str(token_file),
        }
    )
    assert settings.http_bearer_token == "a" * 48

    token_file.chmod(0o644)
    with pytest.raises(ValueError, match="group or other"):
        load_settings(
            {
                "MIKRUS_API_KEY": "k",
                "MIKRUS_SERVER_NAME": "srv",
                "MCP_TRANSPORT": "streamable-http",
                "MCP_HTTP_BEARER_TOKEN_FILE": str(token_file),
            }
        )
