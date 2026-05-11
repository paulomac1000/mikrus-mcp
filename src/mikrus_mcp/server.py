"""MCP server implementation — multi-server with stdio and SSE transport."""

import asyncio
import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp.server import FastMCP
from mcp.server.stdio import stdio_server

from mikrus_mcp.client import MikrusClient, SshClient
from mikrus_mcp.config import load_config
from mikrus_mcp.tools.container_journal import register_container_journal_tools
from mikrus_mcp.tools.discovery import register_discovery_tools
from mikrus_mcp.tools.mikrus_api import register_mikrus_tools
from mikrus_mcp.tools.system import register_system_tools

logger = logging.getLogger(__name__)

# Module-level lifespan reference — set by app_lifespan, read by REST bridge
_lifespan_context: dict[str, Any] | None = None


def _setup_logging() -> None:
    """Configure stderr logging with level from LOG_LEVEL env var."""
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )


async def _init_clients() -> dict[str, Any]:
    """Create and open clients for all configured servers.

    Returns lifespan data dict: {clients, failed, default}.
    Raises RuntimeError if no server could be connected.
    """
    config = load_config()
    clients: dict[str, MikrusClient | SshClient] = {}
    failed: dict[str, str] = {}

    for srv_name, srv_cfg in config["servers"].items():
        client: MikrusClient | SshClient
        try:
            if srv_cfg["type"] == "mikrus":
                client = MikrusClient(
                    base_url=srv_cfg["api_url"],
                    api_key=srv_cfg["key"],
                    server_name=srv_cfg["srv"],
                )
            else:
                client = SshClient(
                    host=srv_cfg["host"],
                    user=srv_cfg.get("user", "root"),
                    port=srv_cfg.get("port", 22),
                    ssh_key=srv_cfg.get("ssh_key"),
                    ssh_cert=srv_cfg.get("ssh_cert"),
                    password=srv_cfg.get("password"),
                    sudo_password=srv_cfg.get("sudo_password"),
                    timeout=srv_cfg.get("timeout", 30),
                    verify_host_key=srv_cfg.get("verify_host_key", False),
                    known_hosts_file=srv_cfg.get("known_hosts_file"),
                )
            await client.open()
            clients[srv_name] = client
            logger.info("Connected to %s (%s)", srv_name, srv_cfg["type"])
        except Exception as exc:
            logger.error("Failed to connect to %s: %s", srv_name, exc)
            failed[srv_name] = str(exc)

    if not clients:
        raise RuntimeError(f"No servers available. Failed: {failed}")

    if failed:
        logger.warning(
            "Partial startup: %d/%d servers available. Failed: %s",
            len(clients),
            len(config["servers"]),
            list(failed.keys()),
        )

    effective_default = config["default"]
    if effective_default not in clients:
        effective_default = next(iter(clients.keys()))

    return {
        "clients": clients,
        "failed": failed,
        "default": effective_default,
    }


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    """Yield global lifespan context.

    In FastMCP 1.27, lifespan is called per-SSE-connection.
    Clients are initialized globally before the first connection
    via _init_clients() called from main().
    This function is a thin wrapper that yields the pre-initialized data.
    """
    global _lifespan_context
    if _lifespan_context is None:
        _lifespan_context = await _init_clients()
        mcp._lifespan_data = _lifespan_context  # type: ignore[attr-defined]
    yield _lifespan_context


mcp = FastMCP("mikrus-mcp", lifespan=app_lifespan)

# Register all tool categories
register_mikrus_tools(mcp)
register_system_tools(mcp)
register_container_journal_tools(mcp)
register_discovery_tools(mcp)


def _get_client(server: str | None = None) -> MikrusClient | SshClient:
    """Resolve which client to use for a tool call."""
    ctx = mcp.get_context()
    lifespan: dict[str, Any] = ctx.request_context.lifespan_context
    clients: dict[str, MikrusClient | SshClient] = lifespan["clients"]
    default: str = lifespan["default"]
    name = server or default
    if name not in clients:
        raise ValueError(f"Unknown server: {name}. Available: {sorted(clients.keys())}")
    return clients[name]


async def run_stdio() -> None:
    """Run the MCP server over stdio transport."""
    global _lifespan_context

    _lifespan_context = await _init_clients()
    mcp._lifespan_data = _lifespan_context  # type: ignore[attr-defined]

    try:
        async with stdio_server() as (read_stream, write_stream):
            await mcp._mcp_server.run(
                read_stream,
                write_stream,
                mcp._mcp_server.create_initialization_options(),
            )
    finally:
        for c in _lifespan_context["clients"].values():
            try:
                await c.close()
            except Exception as exc:
                logger.error("Error closing client: %s", exc)
        _lifespan_context = None
        mcp._lifespan_data = None  # type: ignore[attr-defined]


def main() -> None:
    """Entry point. Uses SSE transport when MCP_PORT is set, stdio otherwise."""
    _setup_logging()

    port_str = os.getenv("MCP_PORT", "").strip()
    rest_port_str = os.getenv("MCP_REST_PORT", "").strip()

    if port_str:
        host = os.getenv("MCP_HOST", "127.0.0.1")

        if host == "0.0.0.0":  # nosec B104
            logger.critical(
                "SSE transport listening on 0.0.0.0 WITHOUT AUTHENTICATION. "
                "This exposes FULL CONTROL over all configured servers to "
                "ANYONE on the network. Set MCP_HOST=127.0.0.1 or add auth."
            )
            if not os.getenv("MCP_UNSAFE_PUBLIC_ACCESS_CONFIRMED"):
                raise RuntimeError(
                    "Refusing to start on 0.0.0.0 without MCP_UNSAFE_PUBLIC_ACCESS_CONFIRMED=1"
                )

        try:
            port = int(port_str)
            if not 1 <= port <= 65535:
                raise ValueError(f"Port must be 1-65535, got {port}")
        except ValueError as exc:
            raise RuntimeError(f"Invalid MCP_PORT: {port_str}") from exc

        mcp.settings.host = host
        mcp.settings.port = port

        async def _run_sse_with_rest() -> None:
            global _lifespan_context

            _lifespan_context = await _init_clients()
            mcp._lifespan_data = _lifespan_context  # type: ignore[attr-defined]

            if rest_port_str:
                try:
                    rest_port = int(rest_port_str)
                    from mikrus_mcp.rest_bridge import run_rest_bridge

                    rest_task = asyncio.create_task(run_rest_bridge(mcp, rest_port))
                    logger.info("REST bridge listening on 127.0.0.1:%d", rest_port)
                except (ValueError, ImportError) as exc:
                    logger.warning("REST bridge not started: %s", exc)
                    rest_task = None
            else:
                rest_task = None

            try:
                await mcp.run_sse_async()
            finally:
                if rest_task:
                    rest_task.cancel()
                    try:
                        await rest_task
                    except asyncio.CancelledError:
                        pass

                for c in _lifespan_context["clients"].values():
                    try:
                        await c.close()
                    except Exception as exc:
                        logger.error("Error closing client: %s", exc)

                _lifespan_context = None
                mcp._lifespan_data = None  # type: ignore[attr-defined]

        logger.info("Starting MCP server on %s:%s (SSE)", host, port)
        asyncio.run(_run_sse_with_rest())
    else:
        if rest_port_str:
            logger.warning("MCP_REST_PORT ignored — REST bridge only available in SSE mode")

        logger.info("Starting MCP server on stdio")
        asyncio.run(run_stdio())


if __name__ == "__main__":
    main()
