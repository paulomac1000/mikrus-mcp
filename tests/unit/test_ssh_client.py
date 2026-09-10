from __future__ import annotations

import asyncio
import json
import shlex
import sys
import types
from collections import deque
from pathlib import Path
from typing import Any

import pytest

from mikrus_mcp.client import SshClient
from mikrus_mcp.config import TargetConfig
from mikrus_mcp.errors import AppError, ErrorCode


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
        self.wait_count = 0

    async def wait(self) -> None:
        self.wait_count += 1
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
    assert process.wait_count >= 1


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
async def test_execute_program_keeps_typed_values_out_of_remote_command() -> None:
    process = FakeProcess([json.dumps({"output": "ok", "stderr": "", "exit_code": 0}).encode()])
    connection = FakeConnection(process)
    client = SshClient(ssh_target())
    client._connection = connection

    result = await client.execute_program(
        "printf",
        ["%s", "value with spaces; and symbols"],
        cwd="/tmp",
        stdin="input",
    )

    command = connection.commands[0][0]
    assert "value with spaces" not in command
    assert "printf" not in command
    payload = json.loads(bytes(process.stdin.data))
    assert payload == {
        "executable": "printf",
        "argv": ["%s", "value with spaces; and symbols"],
        "cwd": "/tmp",
        "stdin": "input",
    }
    assert result == {"output": "ok", "stderr": "", "exit_code": 0}


@pytest.mark.asyncio
async def test_remote_job_start_keeps_request_values_in_json_stdin() -> None:
    process = FakeProcess([json.dumps({"jobId": "job", "state": "queued"}).encode()])
    connection = FakeConnection(process)
    client = SshClient(ssh_target())
    client._connection = connection

    result = await client.remote_job_start(
        job_id="job_123456789012345678901234567890",
        request_digest="a" * 64,
        executable="printf",
        argv=["value with spaces; and symbols"],
        cwd="/tmp",
        stdin="input",
    )

    command = connection.commands[0][0]
    assert "value with spaces" not in command
    payload = json.loads(bytes(process.stdin.data))
    assert payload["operation"] == "start"
    assert payload["executable"] == "printf"
    assert payload["argv"] == ["value with spaces; and symbols"]
    assert result == {"jobId": "job", "state": "queued"}


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


@pytest.mark.asyncio
async def test_analyze_disk_fails_on_non_zero_exit_code() -> None:
    process = FakeProcess([b""], stderr=[b"Permission denied"])
    process.exit_status = 1
    connection = FakeConnection(process)
    client = SshClient(ssh_target())
    client._connection = connection

    with pytest.raises(AppError) as exc_info:
        await client.analyze_disk("/root")
    assert exc_info.value.code == ErrorCode.UPSTREAM
    assert "disk analysis failed with exit code 1" in exc_info.value.message
    assert "Permission denied" in exc_info.value.message


def _run_helper(
    helper: str, payload: dict[str, Any], *, env_path: str | None = None
) -> dict[str, Any]:
    import os
    import subprocess

    environment = dict(os.environ)
    if env_path is not None:
        environment["PATH"] = env_path + os.pathsep + environment.get("PATH", "")
    completed = subprocess.run(
        [sys.executable, "-c", helper],
        input=json.dumps(payload).encode("utf-8"),
        capture_output=True,
        env=environment,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr.decode()
    return json.loads(completed.stdout.decode())


def test_file_patch_helper_replaces_file_with_bounded_evidence(tmp_path: Path) -> None:
    import base64
    import hashlib

    from mikrus_mcp.clients import ssh as ssh_module

    target = tmp_path / "srv" / "config.txt"
    target.parent.mkdir()
    target.write_bytes(b"current-bytes")
    before_digest = "sha256:" + hashlib.sha256(b"current-bytes").hexdigest()
    new_bytes = b"replacement\x00binary\xff"
    result = _run_helper(
        ssh_module._FILE_PATCH_HELPER,
        {
            "path": str(target),
            "expected_digest": before_digest,
            "content_b64": base64.b64encode(new_bytes).decode("ascii"),
        },
    )
    assert result["status"] == "REPLACED"
    assert result["before_digest"] == before_digest
    assert result["after_digest"] == "sha256:" + hashlib.sha256(new_bytes).hexdigest()
    assert result["before_size"] == 13
    assert result["after_size"] == len(new_bytes)
    assert target.read_bytes() == new_bytes
    assert target.stat().st_mode & 0o077 == 0


def test_file_patch_helper_conflict_does_not_write(tmp_path: Path) -> None:
    import base64
    import hashlib

    from mikrus_mcp.clients import ssh as ssh_module

    target = tmp_path / "srv" / "config.txt"
    target.parent.mkdir()
    target.write_bytes(b"original")
    result = _run_helper(
        ssh_module._FILE_PATCH_HELPER,
        {
            "path": str(target),
            "expected_digest": "sha256:" + "0" * 64,
            "content_b64": base64.b64encode(b"must-not-appear").decode("ascii"),
        },
    )
    assert result["error"] == "CONFLICT"
    assert result["before_digest"] == "sha256:" + hashlib.sha256(b"original").hexdigest()
    assert target.read_bytes() == b"original"


def test_file_patch_helper_rejects_symlinks_and_missing_targets(tmp_path: Path) -> None:
    import base64

    from mikrus_mcp.clients import ssh as ssh_module

    directory = tmp_path / "srv"
    directory.mkdir()
    linked = directory / "linked.txt"
    linked.symlink_to("/etc/hostname")
    symlink_result = _run_helper(
        ssh_module._FILE_PATCH_HELPER,
        {
            "path": str(linked),
            "expected_digest": "sha256:" + "0" * 64,
            "content_b64": base64.b64encode(b"x").decode("ascii"),
        },
    )
    assert symlink_result["error"] == "SYMLINK_REJECTED"

    missing_result = _run_helper(
        ssh_module._FILE_PATCH_HELPER,
        {
            "path": str(directory / "absent.txt"),
            "expected_digest": "sha256:" + "0" * 64,
            "content_b64": base64.b64encode(b"x").decode("ascii"),
        },
    )
    assert missing_result["error"] == "NOT_FOUND"


def test_cron_helper_read_install_and_concurrent_modification(tmp_path: Path) -> None:
    from mikrus_mcp.clients import ssh as ssh_module
    from mikrus_mcp.cron_profiles import desired_digest, generate_cron_line

    crontab_file = tmp_path / "crontab.txt"
    crontab_file.write_text("# user entry\n0 0 * * * existing-job\n")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    crontab_stub = fake_bin / "crontab"
    crontab_stub.write_text(
        "#!/bin/sh\n"
        f'if [ "$1" = "-l" ]; then cat "{crontab_file}"; exit 0; fi\n'
        f'if [ "$1" = "-" ]; then cat > "{crontab_file}"; exit 0; fi\n'
        "exit 1\n"
    )
    crontab_stub.chmod(0o755)

    def helper_env() -> str:
        return str(fake_bin)

    read = _run_helper(ssh_module._CRON_HELPER, {"operation": "read"}, env_path=helper_env())
    assert read["text"].startswith("# user entry\n")
    assert len(read["hash"]) == 64

    generated = generate_cron_line(
        schedule={
            "minute": "0",
            "hour": "3",
            "day_of_month": "*",
            "month": "*",
            "day_of_week": "1-5",
        },
        executable="grep",
        argv=["--count"],
        environment={},
    )
    marker = f"# mikrus-mcp:backup:sha256={desired_digest(generated)}"
    new_text = read["text"] + f"{marker}\n{generated}\n"
    installed = _run_helper(
        ssh_module._CRON_HELPER,
        {"operation": "install", "expected_hash": read["hash"], "new_text": new_text},
        env_path=helper_env(),
    )
    assert installed["status"] == "INSTALLED"
    assert crontab_file.read_text() == new_text

    stale = _run_helper(
        ssh_module._CRON_HELPER,
        {"operation": "install", "expected_hash": read["hash"], "new_text": "x\n"},
        env_path=helper_env(),
    )
    assert stale["error"] == "CONCURRENT_MODIFICATION"
    assert crontab_file.read_text() == new_text


@pytest.mark.asyncio
async def test_file_patch_atomic_keeps_values_out_of_remote_command() -> None:
    process = FakeProcess(
        [json.dumps({"status": "REPLACED", "before_size": 1, "after_size": 2}).encode()]
    )
    connection = FakeConnection(process)
    client = SshClient(ssh_target())
    client._connection = connection

    result = await client.file_patch_atomic(
        path="/tmp/srv/file with space.txt",
        expected_digest="sha256:" + "a" * 64,
        content_b64="SGVsbG8=",
    )

    command = connection.commands[0][0]
    assert command.startswith("python3 -c ")
    assert "file with space" not in command
    assert "a" * 64 not in command
    assert "SGVsbG8" not in command
    payload = json.loads(bytes(process.stdin.data))
    assert payload == {
        "path": "/tmp/srv/file with space.txt",
        "expected_digest": "sha256:" + "a" * 64,
        "content_b64": "SGVsbG8=",
    }
    assert result["status"] == "REPLACED"


@pytest.mark.asyncio
async def test_file_patch_atomic_maps_conflict_to_conflict_error() -> None:
    process = FakeProcess([json.dumps({"error": "CONFLICT"}).encode()])
    connection = FakeConnection(process)
    client = SshClient(ssh_target())
    client._connection = connection

    with pytest.raises(AppError) as exc_info:
        await client.file_patch_atomic(
            path="/tmp/f", expected_digest="sha256:" + "a" * 64, content_b64=""
        )
    assert exc_info.value.code == ErrorCode.CONFLICT


@pytest.mark.asyncio
async def test_cron_calls_travel_via_json_stdin_only() -> None:
    process = FakeProcess([json.dumps({"text": "", "hash": "b" * 64, "size": 0}).encode()])
    connection = FakeConnection(process)
    client = SshClient(ssh_target())
    client._connection = connection

    read = await client.cron_read()
    command = connection.commands[0][0]
    assert command.startswith("python3 -c ")
    assert "b" * 64 not in command
    assert json.loads(bytes(process.stdin.data)) == {"operation": "read"}
    assert read["hash"] == "b" * 64

    install_process = FakeProcess(
        [json.dumps({"status": "INSTALLED", "hash": "c" * 64, "size": 5}).encode()]
    )
    install_connection = FakeConnection(install_process)
    client._connection = install_connection
    new_text = "0 3 * * 1-5 'grep'\n"
    installed = await client.cron_install(expected_hash="b" * 64, new_text=new_text)
    from mikrus_mcp.clients import ssh as ssh_module

    install_command = install_connection.commands[0][0]
    assert install_command == "python3 -c " + shlex.quote(ssh_module._CRON_HELPER)
    assert new_text not in install_command
    payload = json.loads(bytes(install_process.stdin.data))
    assert payload["operation"] == "install"
    assert payload["expected_hash"] == "b" * 64
    assert payload["new_text"] == new_text
    assert installed["status"] == "INSTALLED"


@pytest.mark.asyncio
async def test_cron_install_maps_concurrent_modification_and_ambiguous() -> None:
    client = SshClient(ssh_target())

    conflict_process = FakeProcess([json.dumps({"error": "CONCURRENT_MODIFICATION"}).encode()])
    client._connection = FakeConnection(conflict_process)
    with pytest.raises(AppError) as conflict:
        await client.cron_install(expected_hash="b" * 64, new_text="x\n")
    assert conflict.value.code == ErrorCode.CONFLICT

    ambiguous_process = FakeProcess([json.dumps({"error": "AMBIGUOUS_OUTCOME"}).encode()])
    client._connection = FakeConnection(ambiguous_process)
    with pytest.raises(AppError) as ambiguous:
        await client.cron_install(expected_hash="b" * 64, new_text="x\n")
    assert ambiguous.value.code == ErrorCode.AMBIGUOUS


@pytest.mark.asyncio
async def test_docker_helper_keeps_arguments_in_typed_argv(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    argv_log = tmp_path / "argv.json"
    docker_stub = fake_bin / "docker"
    argv_snippet = (
        'python3 -c "import json,sys;f=open('
        f"'{argv_log}','a'"
        ');json.dump([sys.argv[1:]],f);f.write(chr(10))" "$@"\n'
    )
    entry1 = json.dumps(
        {
            "ID": "abc123",
            "Names": ["/web-1"],
            "Labels": ("com.docker.compose.project=site,com.docker.compose.service=web"),
        }
    )
    entry2 = json.dumps(
        {
            "ID": "def456",
            "Names": ["/web-2"],
            "Labels": "com.docker.compose.project=other",
        }
    )
    services_payload = json.dumps({"services": {}})
    image_payload = json.dumps({"Id": "sha256:image123"})
    inspect_payload_json = json.dumps({"Id": "abc123def0", "Config": {}})
    docker_stub.write_text(
        "#!/bin/sh\n"
        + argv_snippet
        + 'if [ "$1" = "ps" ]; then\n'
        + f"  echo '{entry1}'\n"
        + "  echo noise-line-not-json\n"
        + f"  echo '{entry2}'\n"
        + 'elif [ "$1" = "compose" ]; then\n'
        + f"  echo '{services_payload}'\n"
        + 'elif [ "$1" = "image" ]; then\n'
        + f"  echo '{image_payload}'\n"
        + 'elif [ "$1" = "inspect" ]; then\n'
        + f"  echo '{inspect_payload_json}'\n"
        + "fi\n"
        + "exit 0\n"
    )
    docker_stub.chmod(0o755)

    from mikrus_mcp.clients import ssh as ssh_module

    filtered = _run_helper(
        ssh_module._DOCKER_HELPER,
        {"operation": "ps_filter", "service": "web", "project": "site"},
        env_path=str(fake_bin),
    )
    assert [item["ID"] for item in filtered["containers"]] == ["abc123", "def456"]

    _run_helper(
        ssh_module._DOCKER_HELPER,
        {
            "operation": "compose_up",
            "project": "site",
            "files": ["/srv/a.yaml", "/srv/b.yaml"],
            "service": "web",
        },
        env_path=str(fake_bin),
    )
    recorded = [json.loads(line) for line in argv_log.read_text().splitlines()]
    up_argv = ["docker", *recorded[1][0]]
    assert up_argv == [
        "docker",
        "compose",
        "-p",
        "site",
        "-f",
        "/srv/a.yaml",
        "-f",
        "/srv/b.yaml",
        "up",
        "-d",
        "--no-deps",
        "--force-recreate",
        "web",
    ]

    config = _run_helper(
        ssh_module._DOCKER_HELPER,
        {"operation": "compose_config", "project": "site", "files": ["/srv/a.yaml"]},
        env_path=str(fake_bin),
    )
    assert config["config"] == {"services": {}}

    image = _run_helper(
        ssh_module._DOCKER_HELPER,
        {"operation": "image_inspect", "image": "nginx:1.27"},
        env_path=str(fake_bin),
    )
    assert image["image"]["Id"] == "sha256:image123"


@pytest.mark.asyncio
async def test_docker_client_methods_travel_via_json_stdin(tmp_path: Path) -> None:
    from mikrus_mcp.clients import ssh as ssh_module

    process = FakeProcess([b"{}"])
    connection = FakeConnection(process)
    client = SshClient(ssh_target())
    client._connection = connection

    await client.docker_ps_filter(service="web", project="site")
    command = connection.commands[0][0]
    assert command == "python3 -c " + shlex.quote(ssh_module._DOCKER_HELPER)
    assert "web" not in command
    assert json.loads(bytes(process.stdin.data)) == {
        "operation": "ps_filter",
        "service": "web",
        "project": "site",
    }

    process = FakeProcess([b"{}"])
    connection = FakeConnection(process)
    client._connection = connection
    await client.docker_compose_up(project="site", files=["/srv/a.yaml"], service="web")
    assert "web" not in connection.commands[0][0]
    assert json.loads(bytes(process.stdin.data))["files"] == ["/srv/a.yaml"]


@pytest.mark.asyncio
async def test_docker_inspect_maps_not_found_and_compose_config_failure(tmp_path: Path) -> None:

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_stub = fake_bin / "docker"
    docker_stub.write_text(
        "#!/bin/sh\n"
        'if [ "$2" = "abc" ]; then echo not-a-json-line; exit 0; fi\n'
        'if [ "$1" = "compose" ]; then echo "compose: invalid file" >&2; exit 1; fi\n'
        "exit 1\n"
    )
    docker_stub.chmod(0o755)

    import os

    environment_path = os.environ.get("PATH", "") + os.pathsep + str(fake_bin)

    process = FakeProcess([json.dumps({"error": "NOT_FOUND"}).encode()])
    connection = FakeConnection(process)
    client = SshClient(ssh_target())
    client._connection = connection
    with pytest.raises(AppError) as missing:
        await client.docker_inspect(["abc"])
    assert missing.value.code == ErrorCode.NOT_FOUND

    process = FakeProcess([json.dumps({"error": "COMPOSE_CONFIG_FAILED"}).encode()])
    connection = FakeConnection(process)
    client._connection = connection
    with pytest.raises(AppError) as failed:
        await client.docker_compose_config(project="site", files=["/srv/a.yaml"])
    assert failed.value.code == ErrorCode.UPSTREAM
    assert environment_path  # helper fixture path prepared for local runs only


def test_remote_job_helper_cancel_reports_terminated(tmp_path: Path) -> None:
    import os
    import subprocess
    import time
    from pathlib import Path as PathLib

    from mikrus_mcp.clients import ssh as ssh_module

    home = tmp_path / "home"
    job_dir = home / ".cache" / "mikrus-mcp" / "remote-jobs" / ("j" * 32)
    job_dir.mkdir(parents=True)
    child = subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(0.2)
    stat_fields = PathLib(f"/proc/{child.pid}/stat").read_text("ascii").split()
    record = {
        "jobId": "j" * 32,
        "state": "running",
        "runtimeIdentity": {
            "pid": str(child.pid),
            "pgid": str(os.getpgid(child.pid)),
            "startTicks": stat_fields[21],
        },
    }
    (job_dir / "record.json").write_text(json.dumps(record))
    environment = dict(os.environ)
    environment["HOME"] = str(home)
    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-c", ssh_module._REMOTE_JOB_HELPER],
        input=json.dumps({"operation": "cancel", "job_id": "j" * 32, "reason": "test"}).encode(),
        capture_output=True,
        env=environment,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr.decode()
    payload = json.loads(completed.stdout.decode())
    assert payload["state"] == "cancelled"
    assert "terminated" in payload
    assert payload["terminated"] is True
    child.wait(timeout=5)
    with pytest.raises(ProcessLookupError):
        os.killpg(os.getpgid(child.pid), 0)


def test_remote_job_helper_cancel_queued_without_identity_skips_signal(
    tmp_path: Path,
) -> None:
    import os
    import subprocess

    from mikrus_mcp.clients import ssh as ssh_module

    home = tmp_path / "home"
    job_dir = home / ".cache" / "mikrus-mcp" / "remote-jobs" / ("q" * 32)
    job_dir.mkdir(parents=True)
    (job_dir / "record.json").write_text(json.dumps({"jobId": "q" * 32, "state": "queued"}))
    environment = dict(os.environ)
    environment["HOME"] = str(home)
    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-c", ssh_module._REMOTE_JOB_HELPER],
        input=json.dumps({"operation": "cancel", "job_id": "q" * 32, "reason": "t"}).encode(),
        capture_output=True,
        env=environment,
        timeout=30,
    )
    payload = json.loads(completed.stdout.decode())
    assert payload["state"] == "cancelled"
    record = json.loads((job_dir / "record.json").read_text())
    assert record["state"] == "cancelled"
    assert "runtimeIdentity" not in record


def test_remote_job_helper_cancel_with_malformed_identity_fails_without_cancel(
    tmp_path: Path,
) -> None:
    import os
    import subprocess

    from mikrus_mcp.clients import ssh as ssh_module

    home = tmp_path / "home"
    job_dir = home / ".cache" / "mikrus-mcp" / "remote-jobs" / ("m" * 32)
    job_dir.mkdir(parents=True)
    (job_dir / "record.json").write_text(
        json.dumps(
            {
                "jobId": "m" * 32,
                "state": "running",
                "runtimeIdentity": {"pid": "not-a-pid", "pgid": "", "startTicks": None},
            }
        )
    )
    environment = dict(os.environ)
    environment["HOME"] = str(home)
    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-c", ssh_module._REMOTE_JOB_HELPER],
        input=json.dumps({"operation": "cancel", "job_id": "m" * 32, "reason": "t"}).encode(),
        capture_output=True,
        env=environment,
        timeout=30,
    )
    payload = json.loads(completed.stdout.decode())
    assert payload["error"] == "CONFLICT"
    assert json.loads((job_dir / "record.json").read_text())["state"] == "running"


def test_remote_job_helper_wait_accepts_zero_timeout(tmp_path: Path) -> None:
    from mikrus_mcp.clients import ssh as ssh_module

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"State": {"Status": "running", "Running": True}}))
    snippet = (
        'if [ "$1" = "inspect" ]; then python3 -c '
        f"\"import json;print(json.dumps(json.load(open('{state_file}'))))\"; fi\n"
    )
    docker_stub = fake_bin / "docker"
    docker_stub.write_text("#!/bin/sh\n" + snippet + "exit 0\n")
    docker_stub.chmod(0o755)

    ready = _run_helper(
        ssh_module._DOCKER_HELPER,
        {
            "operation": "wait",
            "container_id": "abc123",
            "readiness": "running",
            "timeout_seconds": 0,
        },
        env_path=str(fake_bin),
    )
    assert ready["status"] == "READY"
    assert ready["state"] == "running"
