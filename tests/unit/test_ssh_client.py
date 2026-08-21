from __future__ import annotations

import asyncio
import sys
import types
from collections import deque
from typing import Any

import pytest

from mikrus_mcp.client import SshClient
from mikrus_mcp.config import TargetConfig
from mikrus_mcp.errors import AppError


class FakeStream:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = deque(chunks + [b""])

    async def read(self, _: int) -> bytes:
        return self._chunks.popleft()


class FakeStdin:
    def __init__(self) -> None:
        self.data = bytearray()

    def write(self, data: bytes) -> None:
        self.data.extend(data)

    async def drain(self) -> None:
        return None

    def write_eof(self) -> None:
        return None


class FakeProcess:
    def __init__(self, stdout: list[bytes], stderr: list[bytes] | None = None) -> None:
        self.stdout = FakeStream(stdout)
        self.stderr = FakeStream(stderr or [])
        self.stdin = FakeStdin()
        self.exit_status = 0
        self.terminated = False

    async def wait(self) -> None:
        return None

    def terminate(self) -> None:
        self.terminated = True


class FakeHostKey:
    def get_fingerprint(self, algorithm: str = "sha256") -> str:
        assert algorithm == "sha256"
        return "SHA256:test-host-key"


class FakeConnection:
    def __init__(self, process: FakeProcess) -> None:
        self.process = process
        self.commands: list[tuple[str, Any]] = []
        self.closed = False

    def is_closed(self) -> bool:
        return self.closed

    def get_server_host_key(self) -> FakeHostKey:
        return FakeHostKey()

    async def create_process(self, command: str, **kwargs: Any) -> FakeProcess:
        self.commands.append((command, kwargs))
        return self.process

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


def ssh_target(**overrides: Any) -> TargetConfig:
    values: dict[str, Any] = {
        "name": "ssh",
        "type": "ssh",
        "host": "server.example",
        "verify_host_key": True,
    }
    values.update(overrides)
    return TargetConfig(**values)


@pytest.mark.asyncio
async def test_open_uses_default_known_hosts_policy_and_binds_peer_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}
    connection = FakeConnection(FakeProcess([b"ok"]))

    async def connect(**kwargs: Any) -> FakeConnection:
        observed.update(kwargs)
        return connection

    module = types.SimpleNamespace(connect=connect, read_known_hosts=lambda value: value)
    monkeypatch.setitem(sys.modules, "asyncssh", module)
    client = SshClient(ssh_target())
    await client.open()
    assert "known_hosts" not in observed
    assert observed["host"] == "server.example"
    assert client.stable_identity == "ssh:root@server.example:22#host-key=SHA256:test-host-key"
    await client.close()


@pytest.mark.asyncio
async def test_insecure_mode_is_explicit_in_asyncssh_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    async def connect(**kwargs: Any) -> FakeConnection:
        observed.update(kwargs)
        return FakeConnection(FakeProcess([b"ok"]))

    monkeypatch.setitem(
        sys.modules,
        "asyncssh",
        types.SimpleNamespace(connect=connect, read_known_hosts=lambda value: value),
    )
    client = SshClient(ssh_target(verify_host_key=False))
    await client.open()
    assert observed["known_hosts"] is None
    assert client.stable_identity.endswith("#host-key=UNVERIFIED")


@pytest.mark.asyncio
async def test_process_output_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    from mikrus_mcp.clients import ssh as module

    process = FakeProcess([b"x" * 11])
    connection = FakeConnection(process)
    client = SshClient(ssh_target())
    client._connection = connection
    monkeypatch.setattr(module, "MAX_PROCESS_OUTPUT_BYTES", 10)
    with pytest.raises(AppError, match="size limit"):
        await client._run("uptime")
    assert process.terminated is True


@pytest.mark.asyncio
async def test_sudo_password_is_written_to_stdin_not_command() -> None:
    process = FakeProcess([b"journal"])
    connection = FakeConnection(process)
    client = SshClient(ssh_target(sudo_password="very-secret"))
    client._connection = connection
    result = await client._run_sudo("journalctl -n 1")
    command = connection.commands[0][0]
    assert "very-secret" not in command
    assert process.stdin.data == b"very-secret\n"
    assert result["output"] == "journal"


@pytest.mark.asyncio
async def test_file_commands_use_nofollow_atomic_remote_write() -> None:
    read_process = FakeProcess([b"text"])
    read_connection = FakeConnection(read_process)
    read_client = SshClient(ssh_target())
    read_client._connection = read_connection
    await read_client.read_file("/tmp/example.txt")
    read_command = read_connection.commands[0][0]
    assert "realpath -e" in read_command
    assert "/etc/shadow" in read_command
    assert 'head -n 200 -- "$resolved"' in read_command

    write_process = FakeProcess([b"WRITE_OK"])
    write_connection = FakeConnection(write_process)
    write_client = SshClient(ssh_target())
    write_client._connection = write_connection
    await write_client.write_file("/tmp/example.txt", "content")
    write_command = write_connection.commands[0][0]
    assert "python3 -c" in write_command
    assert "O_NOFOLLOW" in write_command
    assert "src_dir_fd=parent_fd" in write_command
    assert "realpath" not in write_command
    assert "mv -fT" not in write_command


def test_ssh_selector_identity_and_timeout_are_derived_from_target_config() -> None:
    target = ssh_target(user="deploy", port=2222, connect_timeout_seconds=17)
    client = SshClient(target)
    assert client.stable_identity == "ssh:deploy@server.example:2222"
    assert client.config.connect_timeout_seconds == 17


class StubbornProcess:
    """Process whose wait() blocks until close() escalates termination."""

    def __init__(self) -> None:
        self.terminated = False
        self.closed = False
        self._closed_event = asyncio.Event()

    def terminate(self) -> None:
        self.terminated = True

    def close(self) -> None:
        self.closed = True
        self._closed_event.set()

    async def wait(self) -> None:
        await self._closed_event.wait()


@pytest.mark.asyncio
async def test_terminate_process_escalates_to_close_within_bounded_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mikrus_mcp.clients import ssh as ssh_module

    monkeypatch.setattr(ssh_module, "SSH_TERMINATE_WAIT_SECONDS", 0.05)
    process = StubbornProcess()
    await SshClient._terminate_process(process)
    assert process.terminated is True
    assert process.closed is True
