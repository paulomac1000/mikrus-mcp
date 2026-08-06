#!/usr/bin/env python3
"""Install and smoke one exact mikrus-mcp wheel in an isolated virtual environment."""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

RUNTIME_REQUIREMENTS = (
    "mcp>=2.0.0,<3",
    "httpx==0.28.1",
    "asyncssh==2.24.0",
    "uvicorn==0.51.0",
)


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
        code = r'''
import asyncio
from mcp.client import Client
from mikrus_mcp.config import Settings, TargetConfig
from mikrus_mcp.server import build_server

async def smoke():
    target = TargetConfig(
        "mock", "mikrus", api_url="https://api.mikr.us", api_key="unused", server_id="mock"
    )
    server = build_server(Settings({"mock": target}, "mock"))
    async with Client(server, raise_exceptions=True) as client:
        listed = await client.list_tools()
        names = {tool.name for tool in listed.tools}
        assert "describe_mikrus_capabilities" in names
        assert "execute_command" not in names
        result = await client.call_tool("describe_mikrus_capabilities", {})
        assert result.is_error is not True
        assert result.structured_content is not None

asyncio.run(smoke())
'''
        subprocess.run([str(python), "-c", code], check=True)
    print(f"Exact wheel smoke passed: {wheel.name} sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
