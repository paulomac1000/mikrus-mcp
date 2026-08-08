#!/usr/bin/env python3
"""Install and smoke one exact mikrus-mcp wheel through real MCP transports."""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

RUNTIME_REQUIREMENTS = (
    "mcp==2.0.0",
    "httpx==0.28.1",
    "asyncssh==2.24.0",
    "uvicorn==0.51.0",
)

TRANSPORT_SMOKE_CODE = r'''
import asyncio
import os
import socket
import sys
import tempfile
from pathlib import Path

import httpx2
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client


def env_base():
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.update(
        {
            "MIKRUS_API_KEY": "artifact-test-key",
            "MIKRUS_SERVER_NAME": "artifact-srv",
            "MCP_WRITE_ENABLED": "0",
        }
    )
    return env


def assert_catalog(result):
    if result.is_error is True or result.structured_content is None:
        raise RuntimeError(f"artifact transport returned an MCP error: {result!r}")
    structured = result.structured_content.get("result", result.structured_content)
    if structured.get("success") is not True:
        raise RuntimeError(f"artifact transport returned an invalid result: {structured!r}")


async def smoke_stdio():
    env = env_base()
    env["MCP_TRANSPORT"] = "stdio"
    params = StdioServerParameters(command=sys.executable, args=["-m", "mikrus_mcp"], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            names = {tool.name for tool in listed.tools}
            if "describe_mikrus_capabilities" not in names or "execute_command" in names:
                raise RuntimeError(f"unexpected exact-wheel tool catalog: {sorted(names)!r}")
            assert_catalog(
                await session.call_tool("describe_mikrus_capabilities", arguments={})
            )


async def wait_for_port(port, process):
    for _ in range(300):
        if process.returncode is not None:
            stderr = await process.stderr.read() if process.stderr is not None else b""
            detail = stderr.decode(errors="replace")
            raise RuntimeError(f"HTTP artifact process exited early: {detail}")
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
        except OSError:
            await asyncio.sleep(0.02)
            continue
        writer.close()
        await writer.wait_closed()
        return
    raise RuntimeError("HTTP artifact process did not become ready")


async def smoke_http():
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = int(probe.getsockname()[1])
    probe.close()
    token = "artifact-http-token-" + "x" * 48
    with tempfile.TemporaryDirectory(prefix="mikrus-http-smoke-") as directory:
        token_file = Path(directory) / "token"
        token_file.write_text(token + "\n", encoding="utf-8")
        token_file.chmod(0o600)
        env = env_base()
        env.update(
            {
                "MCP_TRANSPORT": "streamable-http",
                "MCP_HOST": "127.0.0.1",
                "MCP_PORT": str(port),
                "MCP_HTTP_BEARER_TOKEN_FILE": str(token_file),
            }
        )
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "mikrus_mcp",
            env=env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            await wait_for_port(port, process)
            async with httpx2.AsyncClient(
                headers={"Authorization": f"Bearer {token}"}
            ) as http_client:
                async with streamable_http_client(
                    f"http://127.0.0.1:{port}/mcp", http_client=http_client
                ) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        assert_catalog(
                            await session.call_tool(
                                "describe_mikrus_capabilities", arguments={}
                            )
                        )
        finally:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=10)
                except TimeoutError:
                    process.kill()
                    await process.wait()


async def main():
    await smoke_stdio()
    await smoke_http()


asyncio.run(main())
'''


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--wheel", type=Path, required=True)
    value.add_argument("--wheelhouse", type=Path, required=True)
    return value


def main() -> int:
    args = parser().parse_args()
    wheel = args.wheel.resolve(strict=True)
    wheelhouse = args.wheelhouse.resolve(strict=True)
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="mikrus-wheel-smoke-") as directory:
        root = Path(directory)
        environment = root / "venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(environment)
        python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        base = [str(python), "-m", "pip", "install", "--no-index", f"--find-links={wheelhouse}"]
        subprocess.run([*base, *RUNTIME_REQUIREMENTS], check=True)
        subprocess.run([*base, "--no-deps", str(wheel)], check=True)
        subprocess.run([str(python), "-m", "pip", "check"], check=True)
        subprocess.run([str(python), "-c", TRANSPORT_SMOKE_CODE], check=True)
    print(f"Exact wheel transport smoke passed: {wheel.name} sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
