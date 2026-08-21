#!/usr/bin/env python3
"""Smoke an exact mikrus-mcp container through its real stdio MCP transport."""

from __future__ import annotations

import argparse
import asyncio
import os

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--image", required=True)
    return value


async def smoke(image: str) -> None:
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    parameters = StdioServerParameters(
        command="docker",
        args=[
            "run",
            "--rm",
            "-i",
            "-e",
            "MIKRUS_API_KEY=container-test-key",
            "-e",
            "MIKRUS_SERVER_NAME=container-srv",
            "-e",
            "MCP_TRANSPORT=stdio",
            "-e",
            "MCP_WRITE_ENABLED=1",
            image,
        ],
        env=environment,
    )
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            names = {tool.name for tool in listed.tools}
            if "describe_mikrus_capabilities" not in names or "execute_command" in names:
                raise RuntimeError(f"unexpected container tool catalog: {sorted(names)!r}")
            result = await session.call_tool("describe_mikrus_capabilities", arguments={})
            if result.is_error is True or result.structured_content is None:
                raise RuntimeError(f"container MCP invocation failed: {result!r}")

            configured = await session.call_tool("list_configured_servers", arguments={})
            if configured.is_error is True or configured.structured_content is None:
                raise RuntimeError(f"container local read failed: {configured!r}")

            missing = await session.call_tool(
                "get_server_info", arguments={"server": "missing-target"}
            )
            if missing.is_error is not True:
                raise RuntimeError(f"missing-target failure boundary was not enforced: {missing!r}")

            write_result = await session.call_tool(
                "write_file", arguments={"path": "/srv/artifact-smoke", "content": "x"}
            )
            if write_result.is_error is not True:
                raise RuntimeError(
                    f"container approval boundary was not enforced: {write_result!r}"
                )


def main() -> int:
    args = parser().parse_args()
    asyncio.run(smoke(args.image))
    print(f"Exact container MCP smoke passed: {args.image}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
