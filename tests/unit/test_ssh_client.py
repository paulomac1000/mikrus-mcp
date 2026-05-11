"""Tests for mikrus_mcp SSH client with mocked asyncssh."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mikrus_mcp.client import SshClient
from mikrus_mcp.validators import ValidationError


@pytest.fixture
def client() -> SshClient:
    return SshClient("test-host", "testuser", password="secret", sudo_password="sudo-secret")


@pytest.fixture
def client_no_sudo() -> SshClient:
    return SshClient("test-host", "testuser", password="secret")


@pytest.fixture
def mock_asyncssh() -> MagicMock:
    """Return a mock asyncssh module with all required attributes."""
    mock = MagicMock()
    mock.PIPE = -1
    mock.Error = Exception
    mock.read_known_hosts = MagicMock(return_value=())
    return mock


# ========== Connection tests ==========


@pytest.mark.asyncio
async def test_repr(client: SshClient) -> None:
    assert "testuser@test-host:22" in repr(client)


@pytest.mark.asyncio
async def test_is_connected_false(client: SshClient) -> None:
    assert not client.is_connected


@pytest.mark.asyncio
async def test_open_with_password(client: SshClient, mock_asyncssh: MagicMock) -> None:
    conn_mock = MagicMock()
    conn_mock.is_closed.return_value = False
    conn_mock._transport = MagicMock()
    mock_asyncssh.connect = AsyncMock(return_value=conn_mock)

    with patch.dict("sys.modules", {"asyncssh": mock_asyncssh}):
        await client.open()

    assert client.is_connected
    mock_asyncssh.connect.assert_awaited_once()
    kwargs = mock_asyncssh.connect.call_args.kwargs
    assert kwargs["password"] == "secret"
    assert kwargs["known_hosts"] is None


@pytest.mark.asyncio
async def test_open_with_ssh_key(client: SshClient, mock_asyncssh: MagicMock) -> None:
    client.ssh_key = "/tmp/fake_key"
    client.password = None
    conn_mock = MagicMock()
    conn_mock.is_closed.return_value = False
    conn_mock._transport = MagicMock()
    mock_asyncssh.connect = AsyncMock(return_value=conn_mock)

    with patch.object(Path, "exists", return_value=True):
        with patch.dict("sys.modules", {"asyncssh": mock_asyncssh}):
            await client.open()

    kwargs = mock_asyncssh.connect.call_args.kwargs
    assert kwargs["client_keys"] == ["/tmp/fake_key"]
    assert "password" not in kwargs


@pytest.mark.asyncio
async def test_open_with_ssh_cert(client: SshClient, mock_asyncssh: MagicMock) -> None:
    client.ssh_key = "/tmp/fake_key"
    client.ssh_cert = "/tmp/fake_cert.pub"
    client.password = None
    conn_mock = MagicMock()
    conn_mock.is_closed.return_value = False
    conn_mock._transport = MagicMock()
    mock_asyncssh.connect = AsyncMock(return_value=conn_mock)

    with patch.object(Path, "exists", return_value=True):
        with patch.dict("sys.modules", {"asyncssh": mock_asyncssh}):
            await client.open()

    kwargs = mock_asyncssh.connect.call_args.kwargs
    assert kwargs["client_keys"] == [("/tmp/fake_key", "/tmp/fake_cert.pub")]
    assert "password" not in kwargs


@pytest.mark.asyncio
async def test_open_with_verify_host_key(client: SshClient, mock_asyncssh: MagicMock) -> None:
    client.verify_host_key = True
    client.known_hosts_file = "/tmp/known_hosts"
    conn_mock = MagicMock()
    conn_mock.is_closed.return_value = False
    conn_mock._transport = MagicMock()
    mock_asyncssh.connect = AsyncMock(return_value=conn_mock)

    with patch.dict("sys.modules", {"asyncssh": mock_asyncssh}):
        await client.open()

    kwargs = mock_asyncssh.connect.call_args.kwargs
    assert kwargs["known_hosts"] == ()
    mock_asyncssh.read_known_hosts.assert_called_once_with("/tmp/known_hosts")


@pytest.mark.asyncio
async def test_open_with_verify_host_key_default(
    client: SshClient, mock_asyncssh: MagicMock
) -> None:
    client.verify_host_key = True
    conn_mock = MagicMock()
    conn_mock.is_closed.return_value = False
    conn_mock._transport = MagicMock()
    mock_asyncssh.connect = AsyncMock(return_value=conn_mock)

    with patch.dict("sys.modules", {"asyncssh": mock_asyncssh}):
        await client.open()

    kwargs = mock_asyncssh.connect.call_args.kwargs
    assert kwargs["known_hosts"] == ()


@pytest.mark.asyncio
async def test_close(client: SshClient, mock_asyncssh: MagicMock) -> None:
    conn_mock = MagicMock()
    conn_mock.is_closed.return_value = False
    conn_mock._transport = MagicMock()
    mock_asyncssh.connect = AsyncMock(return_value=conn_mock)

    with patch.dict("sys.modules", {"asyncssh": mock_asyncssh}):
        await client.open()
        await client.close()

    assert not client.is_connected
    conn_mock.close.assert_called_once()


# ========== Command execution tests ==========


@pytest.mark.asyncio
async def test_run_success(client: SshClient, mock_asyncssh: MagicMock) -> None:
    result_mock = MagicMock()
    result_mock.stdout = "hello"
    result_mock.stderr = ""
    result_mock.exit_status = 0
    conn_mock = MagicMock()
    conn_mock.run = AsyncMock(return_value=result_mock)
    conn_mock.is_closed.return_value = False
    conn_mock._transport = MagicMock()
    mock_asyncssh.connect = AsyncMock(return_value=conn_mock)

    with patch.dict("sys.modules", {"asyncssh": mock_asyncssh}):
        await client.open()
        result = await client._run("echo hello")
        await client.close()

    assert result["output"] == "hello"
    assert result["exit_code"] == 0


@pytest.mark.asyncio
async def test_run_error(client: SshClient, mock_asyncssh: MagicMock) -> None:
    conn_mock = MagicMock()
    conn_mock.run = AsyncMock(side_effect=mock_asyncssh.Error("boom"))
    conn_mock.is_closed.return_value = False
    conn_mock._transport = MagicMock()
    mock_asyncssh.connect = AsyncMock(return_value=conn_mock)

    with patch.dict("sys.modules", {"asyncssh": mock_asyncssh}):
        await client.open()
        with pytest.raises(RuntimeError, match="SSH error"):
            await client._run("echo hello")
        await client.close()


@pytest.mark.asyncio
async def test_run_not_opened(client: SshClient) -> None:
    with pytest.raises(RuntimeError, match="not opened"):
        await client._run("echo hello")


# ========== Sudo tests ==========


class _AsyncIter:
    """Helper to mock an async iterable."""

    def __init__(self, items: list[str]) -> None:
        self._items = items

    def __aiter__(self):
        self._index = 0
        return self

    async def __anext__(self) -> str:
        if self._index >= len(self._items):
            raise StopAsyncIteration
        item = self._items[self._index]
        self._index += 1
        return item


@pytest.mark.asyncio
async def test_run_with_sudo(client: SshClient, mock_asyncssh: MagicMock) -> None:
    process_mock = MagicMock()
    process_mock.stdout = _AsyncIter(["output line\n"])
    process_mock.stderr = _AsyncIter(["stderr line\n"])
    process_mock.exit_status = 0
    process_mock.wait = AsyncMock()

    stdin_mock = MagicMock()
    stdin_mock.drain = AsyncMock()
    process_mock.stdin = stdin_mock

    conn_mock = MagicMock()
    conn_mock.create_process = AsyncMock(return_value=process_mock)
    conn_mock.is_closed.return_value = False
    conn_mock._transport = MagicMock()
    mock_asyncssh.connect = AsyncMock(return_value=conn_mock)

    with patch.dict("sys.modules", {"asyncssh": mock_asyncssh}):
        await client.open()
        result = await client._run_with_sudo("whoami")
        await client.close()

    assert result["output"] == "output line\n"
    assert result["exit_code"] == 0
    stdin_mock.write.assert_called_with("sudo-secret\n")


@pytest.mark.asyncio
async def test_run_with_sudo_no_password(
    client_no_sudo: SshClient, mock_asyncssh: MagicMock
) -> None:
    result_mock = MagicMock()
    result_mock.stdout = "root"
    result_mock.stderr = ""
    result_mock.exit_status = 0
    conn_mock = MagicMock()
    conn_mock.run = AsyncMock(return_value=result_mock)
    conn_mock.is_closed.return_value = False
    conn_mock._transport = MagicMock()
    mock_asyncssh.connect = AsyncMock(return_value=conn_mock)

    with patch.dict("sys.modules", {"asyncssh": mock_asyncssh}):
        await client_no_sudo.open()
        result = await client_no_sudo._run_with_sudo("whoami")
        await client_no_sudo.close()

    assert result["output"] == "root"
    conn_mock.run.assert_awaited_once_with("whoami", timeout=client_no_sudo.timeout)


# ========== Public API tests ==========


@pytest.mark.asyncio
async def test_execute_command(client: SshClient, mock_asyncssh: MagicMock) -> None:
    result_mock = MagicMock()
    result_mock.stdout = "hello"
    result_mock.stderr = ""
    result_mock.exit_status = 0
    conn_mock = MagicMock()
    conn_mock.run = AsyncMock(return_value=result_mock)
    conn_mock.is_closed.return_value = False
    conn_mock._transport = MagicMock()
    mock_asyncssh.connect = AsyncMock(return_value=conn_mock)

    with patch.dict("sys.modules", {"asyncssh": mock_asyncssh}):
        await client.open()
        result = await client.execute_command("echo hello")
        await client.close()

    assert result["output"] == "hello"


@pytest.mark.asyncio
async def test_execute_command_dangerous(client: SshClient) -> None:
    with pytest.raises(ValidationError, match="Dangerous"):
        await client.execute_command("rm -rf /")


@pytest.mark.asyncio
async def test_read_file(client: SshClient, mock_asyncssh: MagicMock) -> None:
    result_mock = MagicMock()
    result_mock.stdout = "line1\nline2"
    result_mock.stderr = ""
    result_mock.exit_status = 0
    conn_mock = MagicMock()
    conn_mock.run = AsyncMock(return_value=result_mock)
    conn_mock.is_closed.return_value = False
    conn_mock._transport = MagicMock()
    mock_asyncssh.connect = AsyncMock(return_value=conn_mock)

    with patch.dict("sys.modules", {"asyncssh": mock_asyncssh}):
        await client.open()
        result = await client.read_file("/etc/hosts")
        await client.close()

    assert "line1" in result["output"]
    cmd = conn_mock.run.call_args[0][0]
    assert "cat" in cmd
    assert "hosts" in cmd


@pytest.mark.asyncio
async def test_write_file(client: SshClient, mock_asyncssh: MagicMock) -> None:
    result_mock = MagicMock()
    result_mock.stdout = "WRITE_OK"
    result_mock.stderr = ""
    result_mock.exit_status = 0
    conn_mock = MagicMock()
    conn_mock.run = AsyncMock(return_value=result_mock)
    conn_mock.is_closed.return_value = False
    conn_mock._transport = MagicMock()
    mock_asyncssh.connect = AsyncMock(return_value=conn_mock)

    with patch.dict("sys.modules", {"asyncssh": mock_asyncssh}):
        await client.open()
        result = await client.write_file("/tmp/test.txt", "hello")
        await client.close()

    assert "WRITE_OK" in result["output"]


@pytest.mark.asyncio
async def test_list_docker_containers(client: SshClient, mock_asyncssh: MagicMock) -> None:
    result_mock = MagicMock()
    result_mock.stdout = '{"Names":"c1"}\n{"Names":"c2"}'
    result_mock.stderr = ""
    result_mock.exit_status = 0
    conn_mock = MagicMock()
    conn_mock.run = AsyncMock(return_value=result_mock)
    conn_mock.is_closed.return_value = False
    conn_mock._transport = MagicMock()
    mock_asyncssh.connect = AsyncMock(return_value=conn_mock)

    with patch.dict("sys.modules", {"asyncssh": mock_asyncssh}):
        await client.open()
        result = await client.list_docker_containers()
        await client.close()

    assert result["containers"][0]["Names"] == "c1"


@pytest.mark.asyncio
async def test_get_journal_logs_no_sudo_hint(
    client_no_sudo: SshClient, mock_asyncssh: MagicMock
) -> None:
    result_mock = MagicMock()
    result_mock.stdout = "No journal files were opened due to insufficient permissions."
    result_mock.stderr = ""
    result_mock.exit_status = 1
    conn_mock = MagicMock()
    conn_mock.run = AsyncMock(return_value=result_mock)
    conn_mock.is_closed.return_value = False
    conn_mock._transport = MagicMock()
    mock_asyncssh.connect = AsyncMock(return_value=conn_mock)

    with patch.dict("sys.modules", {"asyncssh": mock_asyncssh}):
        await client_no_sudo.open()
        result = await client_no_sudo.get_journal_logs("ssh.service", 10)
        await client_no_sudo.close()

    assert "requires_elevation" in result
    assert "sudo_password" in result["output"]


@pytest.mark.asyncio
async def test_context_manager(client: SshClient, mock_asyncssh: MagicMock) -> None:
    conn_mock = MagicMock()
    conn_mock.is_closed.return_value = False
    conn_mock._transport = MagicMock()
    mock_asyncssh.connect = AsyncMock(return_value=conn_mock)

    with patch.dict("sys.modules", {"asyncssh": mock_asyncssh}):
        async with client:
            assert client.is_connected

    assert not client.is_connected


# ========== Journal tools with sudo tests ==========


@pytest.mark.asyncio
async def test_get_journal_logs_with_sudo(client: SshClient, mock_asyncssh: MagicMock) -> None:
    process_mock = MagicMock()
    process_mock.stdout = _AsyncIter(["journal entry\n"])
    process_mock.stderr = _AsyncIter([])
    process_mock.exit_status = 0
    process_mock.wait = AsyncMock()
    stdin_mock = MagicMock()
    stdin_mock.drain = AsyncMock()
    process_mock.stdin = stdin_mock

    conn_mock = MagicMock()
    conn_mock.create_process = AsyncMock(return_value=process_mock)
    conn_mock.is_closed.return_value = False
    conn_mock._transport = MagicMock()
    mock_asyncssh.connect = AsyncMock(return_value=conn_mock)

    with patch.dict("sys.modules", {"asyncssh": mock_asyncssh}):
        await client.open()
        result = await client.get_journal_logs("ssh.service", 10)
        await client.close()

    assert "journal entry" in result["output"]
    cmd = conn_mock.create_process.call_args[0][0]
    assert "sudo -S" in cmd
    assert "journalctl" in cmd


@pytest.mark.asyncio
async def test_find_system_errors_with_sudo(client: SshClient, mock_asyncssh: MagicMock) -> None:
    process_mock = MagicMock()
    process_mock.stdout = _AsyncIter(["error msg\n"])
    process_mock.stderr = _AsyncIter([])
    process_mock.exit_status = 0
    process_mock.wait = AsyncMock()
    stdin_mock = MagicMock()
    stdin_mock.drain = AsyncMock()
    process_mock.stdin = stdin_mock

    conn_mock = MagicMock()
    conn_mock.create_process = AsyncMock(return_value=process_mock)
    conn_mock.is_closed.return_value = False
    conn_mock._transport = MagicMock()
    mock_asyncssh.connect = AsyncMock(return_value=conn_mock)

    with patch.dict("sys.modules", {"asyncssh": mock_asyncssh}):
        await client.open()
        result = await client.find_system_errors(2)
        await client.close()

    assert "error msg" in result["output"]
    cmd = conn_mock.create_process.call_args[0][0]
    assert "journalctl -p err" in cmd


@pytest.mark.asyncio
async def test_search_journal_logs_with_sudo(client: SshClient, mock_asyncssh: MagicMock) -> None:
    process_mock = MagicMock()
    process_mock.stdout = _AsyncIter(["matched entry\n"])
    process_mock.stderr = _AsyncIter([])
    process_mock.exit_status = 0
    process_mock.wait = AsyncMock()
    stdin_mock = MagicMock()
    stdin_mock.drain = AsyncMock()
    process_mock.stdin = stdin_mock

    conn_mock = MagicMock()
    conn_mock.create_process = AsyncMock(return_value=process_mock)
    conn_mock.is_closed.return_value = False
    conn_mock._transport = MagicMock()
    mock_asyncssh.connect = AsyncMock(return_value=conn_mock)

    with patch.dict("sys.modules", {"asyncssh": mock_asyncssh}):
        await client.open()
        result = await client.search_journal_logs("failed", 20)
        await client.close()

    assert "matched entry" in result["output"]
    cmd = conn_mock.create_process.call_args[0][0]
    assert "journalctl -q" in cmd


@pytest.mark.asyncio
async def test_run_with_sudo_ssh_error(client: SshClient, mock_asyncssh: MagicMock) -> None:
    conn_mock = MagicMock()
    conn_mock.is_closed.return_value = False
    conn_mock._transport = MagicMock()
    conn_mock.create_process = AsyncMock(side_effect=mock_asyncssh.Error("permission denied"))
    mock_asyncssh.connect = AsyncMock(return_value=conn_mock)

    with patch.dict("sys.modules", {"asyncssh": mock_asyncssh}):
        await client.open()
        with pytest.raises(RuntimeError, match="SSH error"):
            await client._run_with_sudo("whoami")
        await client.close()


@pytest.mark.asyncio
async def test_run_with_sudo_not_opened(client: SshClient) -> None:
    with pytest.raises(RuntimeError, match="not opened"):
        await client._run_with_sudo("whoami")


# ========== SshClient public method tests ==========


@pytest.mark.asyncio
async def test_manage_service_ssh(client: SshClient, mock_asyncssh: MagicMock) -> None:
    result_mock = MagicMock()
    result_mock.stdout = "active (running)"
    result_mock.stderr = ""
    result_mock.exit_status = 0
    conn_mock = MagicMock()
    conn_mock.run = AsyncMock(return_value=result_mock)
    conn_mock.is_closed.return_value = False
    conn_mock._transport = MagicMock()
    mock_asyncssh.connect = AsyncMock(return_value=conn_mock)

    with patch.dict("sys.modules", {"asyncssh": mock_asyncssh}):
        await client.open()
        result = await client.manage_service("nginx", "status")
        await client.close()

    assert "active" in result["output"]


@pytest.mark.asyncio
async def test_manage_service_ssh_invalid(client: SshClient) -> None:
    with pytest.raises(ValidationError, match="Invalid service name"):
        await client.manage_service("rm -rf /", "status")


@pytest.mark.asyncio
async def test_check_port_ssh(client: SshClient, mock_asyncssh: MagicMock) -> None:
    result_mock = MagicMock()
    result_mock.stdout = "PORT_IN_USE"
    result_mock.stderr = ""
    result_mock.exit_status = 0
    conn_mock = MagicMock()
    conn_mock.run = AsyncMock(return_value=result_mock)
    conn_mock.is_closed.return_value = False
    conn_mock._transport = MagicMock()
    mock_asyncssh.connect = AsyncMock(return_value=conn_mock)

    with patch.dict("sys.modules", {"asyncssh": mock_asyncssh}):
        await client.open()
        result = await client.check_port("8080")
        await client.close()

    assert "PORT_IN_USE" in result["output"]


@pytest.mark.asyncio
async def test_manage_process_ssh_kill(client: SshClient, mock_asyncssh: MagicMock) -> None:
    result_mock = MagicMock()
    result_mock.stdout = ""
    result_mock.stderr = ""
    result_mock.exit_status = 0
    conn_mock = MagicMock()
    conn_mock.run = AsyncMock(return_value=result_mock)
    conn_mock.is_closed.return_value = False
    conn_mock._transport = MagicMock()
    mock_asyncssh.connect = AsyncMock(return_value=conn_mock)

    with patch.dict("sys.modules", {"asyncssh": mock_asyncssh}):
        await client.open()
        result = await client.manage_process("node", "kill")
        await client.close()

    assert result["exit_code"] == 0


@pytest.mark.asyncio
async def test_manage_process_ssh_invalid_action(
    client: SshClient,
) -> None:
    with pytest.raises(ValueError, match="Invalid action"):
        await client.manage_process("node", "destroy")


@pytest.mark.asyncio
async def test_manage_process_ssh_kill_no_target(
    client: SshClient,
) -> None:
    with pytest.raises(ValueError, match="target is required"):
        await client.manage_process("", "kill")


@pytest.mark.asyncio
async def test_manage_process_ssh_list(client: SshClient, mock_asyncssh: MagicMock) -> None:
    result_mock = MagicMock()
    result_mock.stdout = "root node"
    result_mock.stderr = ""
    result_mock.exit_status = 0
    conn_mock = MagicMock()
    conn_mock.run = AsyncMock(return_value=result_mock)
    conn_mock.is_closed.return_value = False
    conn_mock._transport = MagicMock()
    mock_asyncssh.connect = AsyncMock(return_value=conn_mock)

    with patch.dict("sys.modules", {"asyncssh": mock_asyncssh}):
        await client.open()
        result = await client.manage_process("", "list")
        await client.close()

    assert "root node" in result["output"]


@pytest.mark.asyncio
async def test_analyze_disk_ssh(client: SshClient, mock_asyncssh: MagicMock) -> None:
    result_mock = MagicMock()
    result_mock.stdout = "/dev/sda1 15G 10G 5G 67%"
    result_mock.stderr = ""
    result_mock.exit_status = 0
    conn_mock = MagicMock()
    conn_mock.run = AsyncMock(return_value=result_mock)
    conn_mock.is_closed.return_value = False
    conn_mock._transport = MagicMock()
    mock_asyncssh.connect = AsyncMock(return_value=conn_mock)

    with patch.dict("sys.modules", {"asyncssh": mock_asyncssh}):
        await client.open()
        result = await client.analyze_disk("/")
        await client.close()

    assert "67%" in result["output"]
    cmd = conn_mock.run.call_args[0][0]
    assert "df -h" in cmd


@pytest.mark.asyncio
async def test_analyze_disk_ssh_invalid_path(
    client: SshClient,
) -> None:
    with pytest.raises(ValueError, match="must be absolute"):
        await client.analyze_disk("relative/path")


@pytest.mark.asyncio
async def test_get_docker_stats_ssh(client: SshClient, mock_asyncssh: MagicMock) -> None:
    result_mock = MagicMock()
    result_mock.stdout = '{"CPUPerc":"5%"}'
    result_mock.stderr = ""
    result_mock.exit_status = 0
    conn_mock = MagicMock()
    conn_mock.run = AsyncMock(return_value=result_mock)
    conn_mock.is_closed.return_value = False
    conn_mock._transport = MagicMock()
    mock_asyncssh.connect = AsyncMock(return_value=conn_mock)

    with patch.dict("sys.modules", {"asyncssh": mock_asyncssh}):
        await client.open()
        result = await client.get_docker_stats()
        await client.close()

    assert result["containers"][0]["CPUPerc"] == "5%"


@pytest.mark.asyncio
async def test_get_docker_logs_ssh(client: SshClient, mock_asyncssh: MagicMock) -> None:
    result_mock = MagicMock()
    result_mock.stdout = "docker log"
    result_mock.stderr = ""
    result_mock.exit_status = 0
    conn_mock = MagicMock()
    conn_mock.run = AsyncMock(return_value=result_mock)
    conn_mock.is_closed.return_value = False
    conn_mock._transport = MagicMock()
    mock_asyncssh.connect = AsyncMock(return_value=conn_mock)

    with patch.dict("sys.modules", {"asyncssh": mock_asyncssh}):
        await client.open()
        result = await client.get_docker_logs("app", 20)
        await client.close()

    assert "docker log" in result["output"]


@pytest.mark.asyncio
async def test_list_directory_ssh(client: SshClient, mock_asyncssh: MagicMock) -> None:
    result_mock = MagicMock()
    result_mock.stdout = "drwxr-xr-x root /tmp"
    result_mock.stderr = ""
    result_mock.exit_status = 0
    conn_mock = MagicMock()
    conn_mock.run = AsyncMock(return_value=result_mock)
    conn_mock.is_closed.return_value = False
    conn_mock._transport = MagicMock()
    mock_asyncssh.connect = AsyncMock(return_value=conn_mock)

    with patch.dict("sys.modules", {"asyncssh": mock_asyncssh}):
        await client.open()
        result = await client.list_directory("/tmp")
        await client.close()

    assert "root" in result["output"]


@pytest.mark.asyncio
async def test_get_memory_info_ssh(client: SshClient, mock_asyncssh: MagicMock) -> None:
    result_mock = MagicMock()
    result_mock.stdout = "Mem: 1G"
    result_mock.stderr = ""
    result_mock.exit_status = 0
    conn_mock = MagicMock()
    conn_mock.run = AsyncMock(return_value=result_mock)
    conn_mock.is_closed.return_value = False
    conn_mock._transport = MagicMock()
    mock_asyncssh.connect = AsyncMock(return_value=conn_mock)

    with patch.dict("sys.modules", {"asyncssh": mock_asyncssh}):
        await client.open()
        result = await client.get_memory_info()
        await client.close()

    assert "Mem" in result["output"]


@pytest.mark.asyncio
async def test_sudo_no_password_returns_run(
    client_no_sudo: SshClient, mock_asyncssh: MagicMock
) -> None:
    result_mock = MagicMock()
    result_mock.stdout = "output"
    result_mock.stderr = ""
    result_mock.exit_status = 0
    conn_mock = MagicMock()
    conn_mock.run = AsyncMock(return_value=result_mock)
    conn_mock.is_closed.return_value = False
    conn_mock._transport = MagicMock()
    conn_mock.create_process = AsyncMock()
    mock_asyncssh.connect = AsyncMock(return_value=conn_mock)

    with patch.dict("sys.modules", {"asyncssh": mock_asyncssh}):
        await client_no_sudo.open()
        result = await client_no_sudo._run_with_sudo("journalctl")
        await client_no_sudo.close()

    assert result["output"] == "output"
    conn_mock.run.assert_awaited()
    conn_mock.create_process.assert_not_awaited()
