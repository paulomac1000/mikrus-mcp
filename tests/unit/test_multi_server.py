"""Tests for multi-server routing and partial startup."""

import io
import json
import logging
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mikrus_mcp.server import _get_client, _init_clients, app_lifespan, mcp


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


# ========== _init_clients tests ==========


@pytest.mark.asyncio
async def test_init_clients_all_connected(mock_config: dict) -> None:
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

                result = await _init_clients()

                assert len(result["clients"]) == 2
                assert "alpha" in result["clients"]
                assert "beta" in result["clients"]
                assert result["default"] == "alpha"
                assert not result["failed"]

                alpha_client.open.assert_awaited_once()
                beta_client.open.assert_awaited_once()


@pytest.mark.asyncio
async def test_init_clients_partial_startup(mock_config_three: dict) -> None:
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

                result = await _init_clients()

                assert len(result["clients"]) == 2
                assert "gamma" in result["failed"]
                assert result["default"] == "alpha"


@pytest.mark.asyncio
async def test_init_clients_default_fallback(mock_config: dict) -> None:
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

                result = await _init_clients()

                assert "alpha" in result["failed"]
                assert "beta" in result["clients"]
                assert result["default"] == "beta"


@pytest.mark.asyncio
async def test_init_clients_all_fail() -> None:
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
                await _init_clients()


@pytest.mark.asyncio
async def test_init_clients_does_not_close() -> None:
    """_init_clients opens but does NOT close -- cleanup is in main()."""
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
            alpha_client = MagicMock()
            alpha_client.open = AsyncMock()
            alpha_client.close = AsyncMock()
            MockMikrus.return_value = alpha_client

            result = await _init_clients()

            assert len(result["clients"]) == 1
            alpha_client.open.assert_awaited_once()
            alpha_client.close.assert_not_called()


@pytest.mark.asyncio
async def test_app_lifespan_is_thin_wrapper() -> None:
    """Verify app_lifespan yields pre-initialized _lifespan_context."""
    mock_data = {"clients": {"a": MagicMock()}, "default": "a", "failed": {}}
    with patch("mikrus_mcp.server._lifespan_context", mock_data):
        with patch("mikrus_mcp.server.mcp"):
            async with app_lifespan(MagicMock()) as ctx:
                assert ctx is mock_data


@pytest.mark.asyncio
async def test_app_lifespan_backward_compat(mock_config: dict) -> None:
    """Verify app_lifespan calls _init_clients when context is None."""
    with patch("mikrus_mcp.server.load_config", return_value=mock_config):
        with patch("mikrus_mcp.server.MikrusClient") as MockMikrus:
            with patch("mikrus_mcp.server.SshClient") as MockSsh:
                alpha_client = MagicMock()
                alpha_client.open = AsyncMock()
                beta_client = MagicMock()
                beta_client.open = AsyncMock()
                MockMikrus.return_value = alpha_client
                MockSsh.return_value = beta_client

                async with app_lifespan(MagicMock()) as ctx:
                    assert len(ctx["clients"]) == 2
                    assert ctx["default"] == "alpha"
                    alpha_client.open.assert_awaited_once()
                    beta_client.open.assert_awaited_once()


def test_setup_logging() -> None:
    """Verify _setup_logging configures stderr logging."""
    from mikrus_mcp.server import _setup_logging

    logger = logging.getLogger("mikrus_mcp")
    old_handlers = list(logger.handlers)
    logger.handlers.clear()

    try:
        with patch("sys.stderr", new_callable=io.StringIO):
            _setup_logging()
            root = logging.getLogger()
            has_stderr = any(
                isinstance(h, logging.StreamHandler) and getattr(h, "stream", None) is not None
                for h in root.handlers
            )
            assert has_stderr, "Expected at least one StreamHandler on stderr"
    finally:
        logger.handlers = old_handlers


@patch("mikrus_mcp.server.asyncio.run")
def test_main_invalid_mcp_port(mock_run: MagicMock) -> None:
    """Verify main() raises on invalid MCP_PORT."""
    from mikrus_mcp.server import main

    with patch.dict(os.environ, {"MCP_PORT": "abc"}, clear=True):
        with pytest.raises(RuntimeError, match="Invalid MCP_PORT"):
            main()


@patch("mikrus_mcp.server.asyncio.run")
def test_main_public_sse_no_confirm(mock_run: MagicMock) -> None:
    """Verify main() refuses 0.0.0.0 without MCP_UNSAFE_PUBLIC_ACCESS_CONFIRMED."""
    from mikrus_mcp.server import main

    with patch.dict(
        os.environ,
        {"MCP_PORT": "9097", "MCP_HOST": "0.0.0.0"},
        clear=True,
    ):
        with pytest.raises(RuntimeError, match="Refusing to start on 0.0.0.0"):
            main()


@patch("mikrus_mcp.server.asyncio.run")
def test_main_stdio_mode(mock_run: MagicMock) -> None:
    """Verify main() runs run_stdio when MCP_PORT is not set."""
    from mikrus_mcp.server import main

    with patch.dict(os.environ, {}, clear=True):
        with patch("mikrus_mcp.server.run_stdio") as mock_run_stdio:
            main()
            mock_run_stdio.assert_called_once()


@patch("mikrus_mcp.server.asyncio.run")
def test_main_stdio_with_rest_port(mock_run: MagicMock) -> None:
    """Verify main() warns when MCP_REST_PORT set without MCP_PORT."""
    from mikrus_mcp.server import main

    with patch.dict(os.environ, {"MCP_REST_PORT": "8301"}, clear=True):
        with patch("mikrus_mcp.server.run_stdio") as mock_run_stdio:
            with patch("mikrus_mcp.server.logger") as mock_logger:
                main()
                mock_run_stdio.assert_called_once()
                mock_logger.warning.assert_any_call(
                    "MCP_REST_PORT ignored — REST bridge only available in SSE mode"
                )


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
        from mikrus_mcp.tools.discovery import list_configured_servers_tool

        result = await list_configured_servers_tool()

    data = json.loads(result)
    assert data["success"] is True
    inner = data["data"]
    assert len(inner["servers"]) == 3
    names = {s["name"] for s in inner["servers"]}
    assert names == {"alpha", "beta", "gamma"}
    gamma = next(s for s in inner["servers"] if s["name"] == "gamma")
    assert gamma["status"] == "failed"
    assert "connection refused" in gamma["error"]
    alpha = next(s for s in inner["servers"] if s["name"] == "alpha")
    assert alpha["is_default"] is True
    beta = next(s for s in inner["servers"] if s["name"] == "beta")
    assert beta["is_default"] is False
