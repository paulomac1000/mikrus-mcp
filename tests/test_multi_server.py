"""Tests for multi-server routing and partial startup."""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mikrus_mcp.server import _get_client, app_lifespan, mcp


@pytest.fixture
def mock_config() -> dict:
    return {
        "servers": {
            "alpha": {
                "type": "mikrus",
                "key": "k1",
                "srv": "alpha",
                "api_url": "https://api.mikr.us",
            },
            "beta": {"type": "ssh", "host": "beta.host", "user": "root"},
        },
        "default": "alpha",
    }


@pytest.fixture
def mock_config_three() -> dict:
    return {
        "servers": {
            "alpha": {
                "type": "mikrus",
                "key": "k1",
                "srv": "alpha",
                "api_url": "https://api.mikr.us",
            },
            "beta": {"type": "ssh", "host": "beta.host", "user": "root"},
            "gamma": {"type": "ssh", "host": "gamma.host", "user": "root"},
        },
        "default": "alpha",
    }


# ========== app_lifespan tests ==========


@pytest.mark.asyncio
async def test_app_lifespan_all_connected(mock_config: dict) -> None:
    with patch("mikrus_mcp.server.load_config", return_value=mock_config):
        with patch("mikrus_mcp.server.MikrusClient") as MockMikrus:
            with patch("mikrus_mcp.server.SshClient") as MockSsh:
                alpha_client = MagicMock()
                alpha_client.open = AsyncMock()
                alpha_client.close = AsyncMock()
                beta_client = MagicMock()
                beta_client.open = AsyncMock()
                beta_client.close = AsyncMock()
                MockMikrus.return_value = alpha_client
                MockSsh.return_value = beta_client

                async with app_lifespan(MagicMock()) as ctx:
                    assert len(ctx["clients"]) == 2
                    assert "alpha" in ctx["clients"]
                    assert "beta" in ctx["clients"]
                    assert ctx["default"] == "alpha"
                    assert not ctx["failed"]

                alpha_client.close.assert_awaited_once()
                beta_client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_app_lifespan_partial_startup(mock_config_three: dict) -> None:
    with patch("mikrus_mcp.server.load_config", return_value=mock_config_three):
        with patch("mikrus_mcp.server.MikrusClient") as MockMikrus:
            with patch("mikrus_mcp.server.SshClient") as MockSsh:
                alpha_client = MagicMock()
                alpha_client.open = AsyncMock()
                alpha_client.close = AsyncMock()
                beta_client = MagicMock()
                beta_client.open = AsyncMock()
                beta_client.close = AsyncMock()
                MockMikrus.return_value = alpha_client
                MockSsh.return_value = beta_client

                # Simulate gamma failing to open
                async def fail_open(*args, **kwargs):
                    raise ConnectionError("gamma down")

                def _ssh_side_effect(**kwargs: Any) -> MagicMock:
                    if kwargs.get("host") == "beta.host":
                        return beta_client
                    return MagicMock(open=fail_open)

                MockSsh.side_effect = _ssh_side_effect

                async with app_lifespan(MagicMock()) as ctx:
                    assert len(ctx["clients"]) == 2
                    assert "gamma" in ctx["failed"]
                    assert ctx["default"] == "alpha"


@pytest.mark.asyncio
async def test_app_lifespan_default_fallback(mock_config: dict) -> None:
    """If the configured default server fails, fallback to first available."""
    with patch("mikrus_mcp.server.load_config", return_value=mock_config):
        with patch("mikrus_mcp.server.MikrusClient") as MockMikrus:
            with patch("mikrus_mcp.server.SshClient") as MockSsh:
                beta_client = MagicMock()
                beta_client.open = AsyncMock()
                beta_client.close = AsyncMock()
                MockSsh.return_value = beta_client

                # Simulate alpha failing to open
                async def fail_open(*args, **kwargs):
                    raise ConnectionError("alpha down")

                alpha_mock = MagicMock(open=fail_open)
                MockMikrus.return_value = alpha_mock

                async with app_lifespan(MagicMock()) as ctx:
                    assert "alpha" in ctx["failed"]
                    assert "beta" in ctx["clients"]
                    assert ctx["default"] == "beta"


@pytest.mark.asyncio
async def test_app_lifespan_all_fail() -> None:
    config = {
        "servers": {
            "alpha": {
                "type": "mikrus",
                "key": "k",
                "srv": "alpha",
                "api_url": "https://api.mikr.us",
            }
        },
        "default": "alpha",
    }
    with patch("mikrus_mcp.server.load_config", return_value=config):
        with patch("mikrus_mcp.server.MikrusClient") as MockMikrus:

            async def fail_open(*args, **kwargs):
                raise ConnectionError("alpha down")

            alpha_mock = MagicMock(open=fail_open)
            MockMikrus.return_value = alpha_mock

            with pytest.raises(RuntimeError, match="No servers available"):
                async with app_lifespan(MagicMock()):
                    pass  # pragma: no cover


@pytest.mark.asyncio
async def test_app_lifespan_close_error(mock_config: dict) -> None:
    """Gracefully handle errors during client close."""
    with patch("mikrus_mcp.server.load_config", return_value=mock_config):
        with patch("mikrus_mcp.server.MikrusClient") as MockMikrus:
            with patch("mikrus_mcp.server.SshClient") as MockSsh:
                alpha_client = MagicMock()
                alpha_client.open = AsyncMock()
                alpha_client.close = AsyncMock(side_effect=RuntimeError("close error"))
                beta_client = MagicMock()
                beta_client.open = AsyncMock()
                beta_client.close = AsyncMock()
                MockMikrus.return_value = alpha_client
                MockSsh.return_value = beta_client

                async with app_lifespan(MagicMock()) as ctx:
                    assert len(ctx["clients"]) == 2

                alpha_client.close.assert_awaited_once()
                beta_client.close.assert_awaited_once()


# ========== _get_client tests ==========


def test_get_client_default() -> None:
    mock_ctx = MagicMock()
    mock_ctx.request_context.lifespan_context = {
        "clients": {"alpha": MagicMock(), "beta": MagicMock()},
        "default": "alpha",
    }
    with patch.object(mcp, "get_context", return_value=mock_ctx):
        client = _get_client()
        assert client is mock_ctx.request_context.lifespan_context["clients"]["alpha"]


def test_get_client_explicit() -> None:
    mock_ctx = MagicMock()
    mock_ctx.request_context.lifespan_context = {
        "clients": {"alpha": MagicMock(), "beta": MagicMock()},
        "default": "alpha",
    }
    with patch.object(mcp, "get_context", return_value=mock_ctx):
        client = _get_client("beta")
        assert client is mock_ctx.request_context.lifespan_context["clients"]["beta"]


def test_get_client_unknown() -> None:
    mock_ctx = MagicMock()
    mock_ctx.request_context.lifespan_context = {
        "clients": {"alpha": MagicMock()},
        "default": "alpha",
    }
    with patch.object(mcp, "get_context", return_value=mock_ctx):
        with pytest.raises(ValueError, match="Unknown server: gamma"):
            _get_client("gamma")


# ========== list_configured_servers tests ==========


@pytest.mark.asyncio
async def test_list_configured_servers_tool() -> None:
    mock_ctx = MagicMock()
    mock_ctx.request_context.lifespan_context = {
        "clients": {"alpha": MagicMock(), "beta": MagicMock()},
        "failed": {"gamma": "connection refused"},
        "default": "alpha",
    }
    with patch.object(mcp, "get_context", return_value=mock_ctx):
        from mikrus_mcp.server import list_configured_servers_tool

        result = await list_configured_servers_tool()

    data = json.loads(result)
    assert len(data["servers"]) == 3
    names = {s["name"] for s in data["servers"]}
    assert names == {"alpha", "beta", "gamma"}
    gamma = next(s for s in data["servers"] if s["name"] == "gamma")
    assert gamma["status"] == "failed"
    assert "connection refused" in gamma["error"]
    alpha = next(s for s in data["servers"] if s["name"] == "alpha")
    assert alpha["is_default"] is True
    beta = next(s for s in data["servers"] if s["name"] == "beta")
    assert beta["is_default"] is False
