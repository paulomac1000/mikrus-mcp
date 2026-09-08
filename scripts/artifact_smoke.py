#!/usr/bin/env python3
"""Install and smoke one exact mikrus-mcp wheel through real MCP transports."""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

RUNTIME_LOCK = Path("requirements-runtime-linux-x64-py312.lock")
_LOCK_ENTRY = re.compile(r"^([A-Za-z0-9._-]+)==([0-9A-Za-z.+-]+) --hash=")


def runtime_requirements(lock_path: Path) -> tuple[str, ...]:
    """Derive the smoke dependency set from the authoritative runtime lock."""
    entries: list[str] = []
    for line in lock_path.read_text(encoding="utf-8").splitlines():
        match = _LOCK_ENTRY.match(line)
        if match is not None:
            entries.append(f"{match.group(1)}=={match.group(2)}")
    if not entries:
        raise SystemExit(f"runtime lock contains no pinned requirements: {lock_path}")
    return tuple(entries)


TRANSPORT_SMOKE_CODE = r"""
import asyncio
import datetime
import ipaddress
import json
import os
import socket
import ssl
import sys
import tempfile
from pathlib import Path

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client


class FakeMikrusUpstream:
    def __init__(self):
        self.paths = []

    async def handle(self, reader, writer):
        try:
            header = await reader.readuntil(b"\r\n\r\n")
            first_line = header.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
            parts = first_line.split(" ")
            path = parts[1] if len(parts) >= 2 else "<invalid>"
            self.paths.append(path)
            content_length = 0
            for line in header.split(b"\r\n")[1:]:
                if line.lower().startswith(b"content-length:"):
                    content_length = int(line.split(b":", 1)[1].strip())
                    break
            if content_length:
                await reader.readexactly(content_length)
            if path == "/info":
                body = json.dumps(
                    {
                        "server_id": "abc123",
                        "imie_id": "abc123",
                        "server_name": None,
                        "expires": "2027-02-13 00:00:00",
                        "expires_storage": None,
                        "param_ram": "1024",
                        "param_disk": "15",
                        "lastlog_panel": "2026-07-08 00:21:18",
                        "mikrus_pro": "nie",
                    }
                ).encode()
                status = b"200 OK"
            else:
                body = json.dumps({"error": "unexpected fake upstream path"}).encode()
                status = b"500 Internal Server Error"
            writer.write(
                b"HTTP/1.1 "
                + status
                + b"\r\nContent-Type: application/json\r\nContent-Length: "
                + str(len(body)).encode()
                + b"\r\nConnection: close\r\n\r\n"
                + body
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()


def make_tls_material(directory):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_file = Path(directory) / "fake-upstream.crt"
    key_file = Path(directory) / "fake-upstream.key"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return cert_file, key_file


def env_base(api_url, cert_file):
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.update(
        {
            "MIKRUS_API_KEY": "artifact-test-key",
            "MIKRUS_SERVER_NAME": "artifact-srv",
            "MIKRUS_API_URL": api_url,
            "SSL_CERT_FILE": str(cert_file),
            "MCP_WRITE_ENABLED": "1",
        }
    )
    return env


def assert_success(result, label):
    if result.is_error is True or result.structured_content is None:
        raise RuntimeError(f"{label} returned an MCP error: {result!r}")
    structured = result.structured_content.get("result", result.structured_content)
    if structured.get("success") is not True:
        raise RuntimeError(f"{label} returned an invalid result: {structured!r}")


def assert_failure(result, label):
    if result.is_error is not True:
        raise RuntimeError(f"{label} unexpectedly succeeded: {result!r}")


async def exercise_session(session, upstream):
    listed = await session.list_tools()
    names = {tool.name for tool in listed.tools}
    if "describe_mikrus_capabilities" not in names or "execute_command" in names:
        raise RuntimeError(f"unexpected exact-wheel tool catalog: {sorted(names)!r}")

    assert_success(
        await session.call_tool("describe_mikrus_capabilities", arguments={}),
        "capability description",
    )
    before_read = len(upstream.paths)
    assert_success(await session.call_tool("get_server_info", arguments={}), "representative read")
    if upstream.paths[before_read:] != ["/info"]:
        raise RuntimeError(
            f"representative read did not hit exact fake upstream once: {upstream.paths!r}"
        )

    before_failure = len(upstream.paths)
    assert_failure(
        await session.call_tool("get_server_info", arguments={"server": "missing-target"}),
        "missing target failure",
    )
    if len(upstream.paths) != before_failure:
        raise RuntimeError("missing-target failure performed backend I/O")

    before_write = len(upstream.paths)
    assert_failure(
        await session.call_tool(
            "write_file", arguments={"path": "/tmp/artifact-smoke", "content": "x"}
        ),
        "approval boundary",
    )
    if len(upstream.paths) != before_write:
        raise RuntimeError("unapproved write performed backend I/O")


async def smoke_stdio(api_url, cert_file, upstream):
    env = env_base(api_url, cert_file)
    env["MCP_TRANSPORT"] = "stdio"
    params = StdioServerParameters(command=sys.executable, args=["-m", "mikrus_mcp"], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await exercise_session(session, upstream)


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


async def smoke_http(api_url, cert_file, upstream):
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = int(probe.getsockname()[1])
    probe.close()
    token = "artifact-http-token-" + "x" * 48
    with tempfile.TemporaryDirectory(prefix="mikrus-http-smoke-") as directory:
        token_file = Path(directory) / "token"
        token_file.write_text(token + "\n", encoding="utf-8")
        token_file.chmod(0o600)
        env = env_base(api_url, cert_file)
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
            async with httpx.AsyncClient(
                headers={"Authorization": f"Bearer {token}"}
            ) as http_client:
                async with streamable_http_client(
                    f"http://127.0.0.1:{port}/mcp", http_client=http_client
                ) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        await exercise_session(session, upstream)
        finally:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=10)
                except TimeoutError:
                    process.kill()
                    await process.wait()


async def main():
    with tempfile.TemporaryDirectory(prefix="mikrus-upstream-smoke-") as directory:
        cert_file, key_file = make_tls_material(directory)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=cert_file, keyfile=key_file)
        upstream = FakeMikrusUpstream()
        server = await asyncio.start_server(upstream.handle, "127.0.0.1", 0, ssl=context)
        port = int(server.sockets[0].getsockname()[1])
        api_url = f"https://127.0.0.1:{port}"
        async with server:
            await smoke_stdio(api_url, cert_file, upstream)
            await smoke_http(api_url, cert_file, upstream)
        if upstream.paths != ["/info", "/info"]:
            raise RuntimeError(f"unexpected fake upstream I/O: {upstream.paths!r}")


asyncio.run(main())
"""


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--wheel", type=Path, required=True)
    value.add_argument("--wheelhouse", type=Path, required=True)
    value.add_argument(
        "--runtime-lock",
        type=Path,
        default=RUNTIME_LOCK,
        help="authoritative runtime lock used to derive smoke dependencies",
    )
    return value


def main() -> int:
    args = parser().parse_args()
    wheel = args.wheel.resolve(strict=True)
    wheelhouse = args.wheelhouse.resolve(strict=True)
    requirements = runtime_requirements(args.runtime_lock.resolve(strict=True))
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="mikrus-wheel-smoke-") as directory:
        root = Path(directory)
        environment = root / "venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(environment)
        python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        base = [str(python), "-m", "pip", "install", "--no-index", f"--find-links={wheelhouse}"]
        subprocess.run([*base, *requirements], check=True)
        subprocess.run([*base, "--no-deps", str(wheel)], check=True)
        subprocess.run([str(python), "-m", "pip", "check"], check=True)
        subprocess.run([str(python), "-c", TRANSPORT_SMOKE_CODE], check=True)
    print(f"Exact wheel transport smoke passed: {wheel.name} sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
