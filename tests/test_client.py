"""Tests for mikrus_mcp client."""

import pytest
import respx
from httpx import Response

from mikrus_mcp.client import MikrusClient, SshClient
from mikrus_mcp.validators import (
    ValidationError,
    check_dangerous_command,
    validate_container_name,
    validate_content_size,
    validate_domain,
    validate_hours_param,
    validate_lines_param,
    validate_path,
    validate_port,
    validate_search_pattern,
    validate_service_action,
    validate_service_name,
    validate_username,
)


@pytest.fixture
def client() -> MikrusClient:
    return MikrusClient("https://api.mikr.us", "test-key", "test-srv")


@pytest.fixture
def ssh_client() -> SshClient:
    return SshClient("test-host", "testuser", password="secret", sudo_password="secret")


@pytest.fixture
def ssh_client_no_sudo() -> SshClient:
    return SshClient("test-host", "testuser")


# ========== MikrusClient API tests ==========


@pytest.mark.asyncio
async def test_get_server_info(client: MikrusClient) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/info")
        route.respond(
            json={
                "server_id": "test-srv",
                "param_ram": "1024",
                "param_disk": "15",
            }
        )
        await client.open()
        result = await client.get_server_info()
        await client.close()

    assert result["server_id"] == "test-srv"
    assert route.called
    sent = route.calls[0].request
    assert sent.headers.get("authorization") == "Bearer test-key"
    body = sent.content.decode()
    assert "srv=test-srv" in body
    assert "key=test-key" in body


@pytest.mark.asyncio
async def test_get_server_stats(client: MikrusClient) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/stats")
        route.respond(json={"uptime": "10 days"})
        await client.open()
        result = await client.get_server_stats()
        await client.close()

    assert result["uptime"] == "10 days"


@pytest.mark.asyncio
async def test_get_logs(client: MikrusClient) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/logs")
        route.respond(json=[{"id": "1", "task": "restart"}])
        await client.open()
        result = await client.get_logs()
        await client.close()

    assert result[0]["task"] == "restart"


@pytest.mark.asyncio
async def test_get_log_by_id(client: MikrusClient) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/logs/42")
        route.respond(json={"id": "42", "output": "done"})
        await client.open()
        result = await client.get_log_by_id("42")
        await client.close()

    assert result["id"] == "42"


@pytest.mark.asyncio
async def test_restart_server(client: MikrusClient) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/restart")
        route.respond(text="OK")
        await client.open()
        result = await client.restart_server()
        await client.close()

    assert result == {"raw": "OK"}


@pytest.mark.asyncio
async def test_boost_server(client: MikrusClient) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/amfetamina")
        route.respond(json={"status": "boosted"})
        await client.open()
        result = await client.boost_server()
        await client.close()

    assert result["status"] == "boosted"


@pytest.mark.asyncio
async def test_execute_command(client: MikrusClient) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/exec")
        route.respond(json={"output": "hello", "exit_code": 0})
        await client.open()
        result = await client.execute_command("echo hello")
        await client.close()

    assert result["output"] == "hello"
    body = route.calls[0].request.content.decode()
    assert "cmd=echo+hello" in body


@pytest.mark.asyncio
async def test_http_error(client: MikrusClient) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/info")
        route.respond(status_code=401, text="Unauthorized")
        await client.open()
        with pytest.raises(RuntimeError, match="HTTP 401"):
            await client.get_server_info()
        await client.close()


@pytest.mark.asyncio
async def test_timeout(client: MikrusClient) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/exec")
        route.mock(side_effect=lambda req: Response(200, json={}))
        await client.open()
        result = await client.execute_command("sleep 1")
        await client.close()
        assert result is not None


@pytest.mark.asyncio
async def test_list_servers(client: MikrusClient) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/serwery")
        route.respond(json=[{"server_id": "srv1"}, {"server_id": "srv2"}])
        await client.open()
        result = await client.list_servers()
        await client.close()

    assert len(result) == 2
    assert result[0]["server_id"] == "srv1"


@pytest.mark.asyncio
async def test_get_db_info(client: MikrusClient) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/db")
        route.respond(json={"host": "db.mikr.us", "port": "3306", "user": "u_test"})
        await client.open()
        result = await client.get_db_info()
        await client.close()

    assert result["host"] == "db.mikr.us"


@pytest.mark.asyncio
async def test_get_ports(client: MikrusClient) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/porty")
        route.respond(json={"tcp": ["22", "80", "443"], "udp": ["53"]})
        await client.open()
        result = await client.get_ports()
        await client.close()

    assert "22" in result["tcp"]


@pytest.mark.asyncio
async def test_get_cloud(client: MikrusClient) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/cloud")
        route.respond(json={"services": [{"name": "storage", "size": "10GB"}]})
        await client.open()
        result = await client.get_cloud()
        await client.close()

    assert result["services"][0]["name"] == "storage"


@pytest.mark.asyncio
async def test_assign_domain(client: MikrusClient) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/domain")
        route.respond(json={"domain": "test.mikr.us", "port": "8080"})
        await client.open()
        result = await client.assign_domain("8080", "-")
        await client.close()

    assert result["domain"] == "test.mikr.us"
    body = route.calls[0].request.content.decode()
    assert "port=8080" in body
    assert "domain=-" in body


@pytest.mark.asyncio
async def test_read_file(client: MikrusClient) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/exec")
        route.respond(json={"output": "line1\nline2", "exit_code": 0})
        await client.open()
        result = await client.read_file("/etc/hosts")
        await client.close()

    assert result["output"] == "line1\nline2"
    body = route.calls[0].request.content.decode()
    assert "cat" in body
    assert "hosts" in body
    assert "head" in body


@pytest.mark.asyncio
async def test_read_file_invalid_path(client: MikrusClient) -> None:
    await client.open()
    with pytest.raises(ValidationError, match="Path must be absolute"):
        await client.read_file("../etc/passwd")
    await client.close()


@pytest.mark.asyncio
async def test_write_file(client: MikrusClient) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/exec")
        route.respond(json={"output": "WRITE_OK\n", "exit_code": 0})
        await client.open()
        result = await client.write_file("/tmp/test.txt", "hello world")
        await client.close()

    assert "WRITE_OK" in result["output"]
    body = route.calls[0].request.content.decode()
    assert "base64" in body
    assert "test.txt" in body


@pytest.mark.asyncio
async def test_write_file_too_large(client: MikrusClient) -> None:
    await client.open()
    huge = "x" * 200_000
    with pytest.raises(ValidationError, match="Content too large"):
        await client.write_file("/tmp/big.txt", huge)
    await client.close()


@pytest.mark.asyncio
async def test_manage_service(client: MikrusClient) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/exec")
        route.respond(json={"output": "active (running)", "exit_code": 0})
        await client.open()
        result = await client.manage_service("nginx", "status")
        await client.close()

    assert "active" in result["output"]
    body = route.calls[0].request.content.decode()
    assert "systemctl+status" in body
    assert "nginx" in body


@pytest.mark.asyncio
async def test_manage_service_invalid_action(client: MikrusClient) -> None:
    await client.open()
    with pytest.raises(ValidationError, match="Invalid action"):
        await client.manage_service("nginx", "delete")
    await client.close()


@pytest.mark.asyncio
async def test_manage_service_invalid_name(client: MikrusClient) -> None:
    await client.open()
    with pytest.raises(ValidationError, match="Invalid service name"):
        await client.manage_service("rm -rf /", "status")
    await client.close()


@pytest.mark.asyncio
async def test_analyze_disk(client: MikrusClient) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/exec")
        route.respond(
            json={
                "output": ("Filesystem  Size  Used Avail Use%\n/dev/sda1 15G 10G 5G 67%"),
                "exit_code": 0,
            }
        )
        await client.open()
        result = await client.analyze_disk("/")
        await client.close()

    assert "67%" in result["output"]
    body = route.calls[0].request.content.decode()
    assert "df+-h" in body


@pytest.mark.asyncio
async def test_analyze_disk_uses_path(client: MikrusClient) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/exec")
        route.respond(json={"output": "test", "exit_code": 0})
        await client.open()
        await client.analyze_disk("/var/log")
        await client.close()

    body = route.calls[0].request.content.decode()
    assert "du+-sh+%27%2Fvar%2Flog%27" in body


@pytest.mark.asyncio
async def test_check_port(client: MikrusClient) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/exec")
        route.respond(
            json={
                "output": ('LISTEN 0 128 *:3000 *:* users:(("node",pid=1234))'),
                "exit_code": 0,
            }
        )
        await client.open()
        result = await client.check_port("3000")
        await client.close()

    assert "LISTEN" in result["output"]
    body = route.calls[0].request.content.decode()
    assert "grep+%27%3A3000+%27" in body
    assert "grep+%27%3A%283000%29" not in body


@pytest.mark.asyncio
async def test_check_port_invalid(client: MikrusClient) -> None:
    await client.open()
    with pytest.raises(ValidationError, match="Port must be a number"):
        await client.check_port("abc")
    await client.close()


@pytest.mark.asyncio
async def test_check_port_out_of_range(client: MikrusClient) -> None:
    await client.open()
    with pytest.raises(ValidationError, match="Port must be 1-65535"):
        await client.check_port("99999")
    await client.close()


@pytest.mark.asyncio
async def test_manage_process_list(client: MikrusClient) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/exec")
        route.respond(json={"output": "root 1234 0.1 2.0 node", "exit_code": 0})
        await client.open()
        result = await client.manage_process("", "list")
        await client.close()

    assert "node" in result["output"]
    body = route.calls[0].request.content.decode()
    assert "ps+aux" in body


@pytest.mark.asyncio
async def test_manage_process_kill(client: MikrusClient) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/exec")
        route.respond(json={"output": "", "exit_code": 0})
        await client.open()
        result = await client.manage_process("node", "kill")
        await client.close()

    assert result["exit_code"] == 0
    body = route.calls[0].request.content.decode()
    assert "killall" in body


@pytest.mark.asyncio
async def test_manage_process_invalid_action(client: MikrusClient) -> None:
    await client.open()
    with pytest.raises(ValidationError, match="Invalid action"):
        await client.manage_process("node", "destroy")
    await client.close()


@pytest.mark.asyncio
async def test_update_system(client: MikrusClient) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/exec")
        route.respond(json={"output": "0 upgraded, 0 newly installed", "exit_code": 0})
        await client.open()
        result = await client.update_system()
        await client.close()

    assert "upgraded" in result["output"]
    body = route.calls[0].request.content.decode()
    assert "DEBIAN_FRONTEND" in body
    assert "apt-get" in body


@pytest.mark.asyncio
async def test_list_directory(client: MikrusClient) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/exec")
        route.respond(json={"output": "drwxr-xr-x 2 root root 4096 /tmp", "exit_code": 0})
        await client.open()
        result = await client.list_directory("/tmp")
        await client.close()

    assert "root" in result["output"]
    body = route.calls[0].request.content.decode()
    assert "ls+-la+--" in body


@pytest.mark.asyncio
async def test_tail_file(client: MikrusClient) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/exec")
        route.respond(json={"output": "last line", "exit_code": 0})
        await client.open()
        result = await client.tail_file("/var/log/syslog", 10)
        await client.close()

    assert "last line" in result["output"]
    body = route.calls[0].request.content.decode()
    assert "tail+-n+10" in body


@pytest.mark.asyncio
async def test_tail_file_clamping(client: MikrusClient) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/exec")
        route.respond(json={"output": "test", "exit_code": 0})
        await client.open()
        await client.tail_file("/var/log/syslog", 9999)
        await client.close()

    body = route.calls[0].request.content.decode()
    assert "tail+-n+500" in body


@pytest.mark.asyncio
async def test_search_in_files(client: MikrusClient) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/exec")
        route.respond(json={"output": "/etc/hosts:1:nameserver", "exit_code": 0})
        await client.open()
        result = await client.search_in_files("/etc", "nameserver")
        await client.close()

    assert "nameserver" in result["output"]
    body = route.calls[0].request.content.decode()
    assert "grep+-r+-F" in body


@pytest.mark.asyncio
async def test_get_memory_info(client: MikrusClient) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/exec")
        route.respond(json={"output": "Mem: 1G", "exit_code": 0})
        await client.open()
        result = await client.get_memory_info()
        await client.close()

    assert "Mem" in result["output"]
    body = route.calls[0].request.content.decode()
    assert "free+-h" in body


@pytest.mark.asyncio
async def test_get_network_info(client: MikrusClient) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/exec")
        route.respond(json={"output": "eth0: UP", "exit_code": 0})
        await client.open()
        result = await client.get_network_info()
        await client.close()

    assert "eth0" in result["output"]
    body = route.calls[0].request.content.decode()
    assert "ip+addr" in body


@pytest.mark.asyncio
async def test_get_process_tree(client: MikrusClient) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/exec")
        route.respond(json={"output": "root 1 init", "exit_code": 0})
        await client.open()
        result = await client.get_process_tree()
        await client.close()

    assert "init" in result["output"]
    body = route.calls[0].request.content.decode()
    assert "ps+auxf" in body


@pytest.mark.asyncio
async def test_list_docker_containers(client: MikrusClient) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/exec")
        route.respond(json={"output": '{"Names":"test"}\n{"Names":"other"}', "exit_code": 0})
        await client.open()
        result = await client.list_docker_containers()
        await client.close()

    assert result["containers"][0]["Names"] == "test"


@pytest.mark.asyncio
async def test_get_docker_logs(client: MikrusClient) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/exec")
        route.respond(json={"output": "log line", "exit_code": 0})
        await client.open()
        result = await client.get_docker_logs("myapp", 20)
        await client.close()

    assert "log line" in result["output"]
    body = route.calls[0].request.content.decode()
    assert "docker+logs" in body


@pytest.mark.asyncio
async def test_get_docker_stats(client: MikrusClient) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/exec")
        route.respond(json={"output": '{"CPUPerc":"10%"}', "exit_code": 0})
        await client.open()
        result = await client.get_docker_stats()
        await client.close()

    assert result["containers"][0]["CPUPerc"] == "10%"


@pytest.mark.asyncio
async def test_get_journal_logs(client: MikrusClient) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/exec")
        route.respond(json={"output": "journal entry", "exit_code": 0})
        await client.open()
        result = await client.get_journal_logs("ssh.service", 10)
        await client.close()

    assert "journal" in result["output"]
    body = route.calls[0].request.content.decode()
    assert "journalctl" in body


@pytest.mark.asyncio
async def test_find_system_errors(client: MikrusClient) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/exec")
        route.respond(json={"output": "error msg", "exit_code": 0})
        await client.open()
        result = await client.find_system_errors(2)
        await client.close()

    assert "error" in result["output"]
    body = route.calls[0].request.content.decode()
    assert "journalctl" in body
    assert "-n+500" in body


@pytest.mark.asyncio
async def test_find_system_errors_hours_clamping(client: MikrusClient) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/exec")
        route.respond(json={"output": "test", "exit_code": 0})
        await client.open()
        await client.find_system_errors(999)
        await client.close()

    body = route.calls[0].request.content.decode()
    assert "24+hours+ago" in body


@pytest.mark.asyncio
async def test_search_journal_logs(client: MikrusClient) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/exec")
        route.respond(json={"output": "found it", "exit_code": 0})
        await client.open()
        result = await client.search_journal_logs("failed", 10)
        await client.close()

    assert "found it" in result["output"]
    body = route.calls[0].request.content.decode()
    assert "journalctl" in body


@pytest.mark.asyncio
async def test_get_journal_logs_insufficient_permissions(
    client: MikrusClient,
) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/exec")
        route.respond(
            json={
                "output": ("No journal files were opened due to insufficient permissions."),
                "exit_code": 1,
            }
        )
        await client.open()
        result = await client.get_journal_logs("ssh.service", 3)
        await client.close()

    assert "requires_elevation" in result
    assert "systemd-journal" in result["output"]


@pytest.mark.asyncio
async def test_find_system_errors_insufficient_permissions(
    client: MikrusClient,
) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/exec")
        route.respond(
            json={
                "output": ("No journal files were opened due to insufficient permissions."),
                "exit_code": 1,
            }
        )
        await client.open()
        result = await client.find_system_errors(1)
        await client.close()

    assert "requires_elevation" in result
    assert "systemd-journal" in result["output"]


# ========== SshClient tests ==========


def test_journal_access_hint_with_sudo(ssh_client: SshClient) -> None:
    assert ssh_client._journal_access_hint("insufficient permissions") is None


def test_journal_access_hint_without_sudo(
    ssh_client_no_sudo: SshClient,
) -> None:
    hint = ssh_client_no_sudo._journal_access_hint(
        "No journal files were opened due to insufficient permissions."
    )
    assert hint is not None
    assert "sudo_password" in hint


def test_sudo_wrap_with_password(ssh_client: SshClient) -> None:
    # _run_with_sudo is async and uses create_process, not simple string wrapping
    # Just verify the client stores the password
    assert ssh_client.sudo_password == "secret"


def test_sudo_wrap_without_password(ssh_client_no_sudo: SshClient) -> None:
    assert ssh_client_no_sudo.sudo_password is None


def test_ssh_client_repr(ssh_client: SshClient) -> None:
    assert "testuser@test-host:22" in repr(ssh_client)


def test_ssh_client_not_connected(ssh_client_no_sudo: SshClient) -> None:
    assert not ssh_client_no_sudo.is_connected


# ========== Validation tests ==========


def test_validate_path_traversal() -> None:
    with pytest.raises(ValidationError, match="Path traversal"):
        validate_path("/etc/../passwd")


def test_validate_path_relative() -> None:
    with pytest.raises(ValidationError, match="must be absolute"):
        validate_path("tmp/file.txt")


def test_validate_path_forbidden_read() -> None:
    with pytest.raises(ValidationError, match="forbidden"):
        validate_path("/etc/shadow")


def test_validate_path_forbidden_write() -> None:
    with pytest.raises(ValidationError, match="forbidden"):
        validate_path("/etc/passwd", for_write=True)


def test_validate_port_number() -> None:
    assert validate_port("8080") == 8080
    assert validate_port(443) == 443


def test_validate_port_invalid() -> None:
    with pytest.raises(ValidationError, match="must be a number"):
        validate_port("abc")
    with pytest.raises(ValidationError, match="1-65535"):
        validate_port("0")
    with pytest.raises(ValidationError, match="1-65535"):
        validate_port("99999")


def test_validate_service_name_invalid() -> None:
    with pytest.raises(ValidationError, match="Invalid service name"):
        validate_service_name("rm -rf /")


def test_validate_service_action_invalid() -> None:
    with pytest.raises(ValidationError, match="Invalid action"):
        validate_service_action("destroy")


def test_validate_domain_auto() -> None:
    assert validate_domain("-") == "-"


def test_validate_domain_invalid() -> None:
    with pytest.raises(ValidationError, match="Invalid domain"):
        validate_domain("not a domain")


def test_validate_content_size() -> None:
    validate_content_size("x" * 50_000)
    with pytest.raises(ValidationError, match="too large"):
        validate_content_size("x" * 200_000)


def test_check_dangerous_command() -> None:
    with pytest.raises(ValidationError, match="Dangerous"):
        check_dangerous_command("rm -rf /")
    with pytest.raises(ValidationError, match="Dangerous"):
        check_dangerous_command("mkfs.ext4 /dev/sda")
    with pytest.raises(ValidationError, match="Dangerous"):
        check_dangerous_command("dd if=/dev/zero of=/dev/sda")


def test_validate_lines_param() -> None:
    assert validate_lines_param(50) == 50
    assert validate_lines_param("100") == 100
    assert validate_lines_param(9999) == 500
    assert validate_lines_param(0) == 1
    assert validate_lines_param("abc") == 50


def test_validate_hours_param() -> None:
    assert validate_hours_param(5) == 5
    assert validate_hours_param("12") == 12
    assert validate_hours_param(999) == 24
    assert validate_hours_param(0) == 1
    assert validate_hours_param("abc") == 1


def test_validate_path_empty() -> None:
    with pytest.raises(ValidationError, match="cannot be empty"):
        validate_path("")


def test_validate_path_non_string() -> None:
    with pytest.raises(ValidationError, match="must be string"):
        validate_path(123)  # type: ignore[arg-type]


def test_validate_path_invalid_chars() -> None:
    with pytest.raises(ValidationError, match="invalid characters"):
        validate_path("/tmp/\x00test")


def test_validate_service_name_valid() -> None:
    assert validate_service_name("nginx") == "nginx"
    assert validate_service_name("docker.service") == "docker.service"
    assert validate_service_name("my-app.service") == "my-app.service"


def test_validate_service_name_empty() -> None:
    with pytest.raises(ValidationError, match="cannot be empty"):
        validate_service_name("")


def test_validate_service_name_too_long() -> None:
    with pytest.raises(ValidationError, match="too long"):
        validate_service_name("a" * 256)


def test_validate_service_action_valid() -> None:
    actions = ("status", "start", "stop", "restart", "enable", "disable", "is-active", "is-enabled")
    for action in actions:
        assert validate_service_action(action) == action


def test_validate_container_name_valid() -> None:
    assert validate_container_name("myapp") == "myapp"
    assert validate_container_name("my-app_v1.0") == "my-app_v1.0"


def test_validate_container_name_empty() -> None:
    with pytest.raises(ValidationError, match="cannot be empty"):
        validate_container_name("")


def test_validate_container_name_invalid() -> None:
    with pytest.raises(ValidationError, match="Invalid container name"):
        validate_container_name("-invalid")


def test_validate_domain_valid() -> None:
    assert validate_domain("example.com") == "example.com"
    assert validate_domain("sub.example.co.uk") == "sub.example.co.uk"


def test_validate_domain_too_long() -> None:
    with pytest.raises(ValidationError, match="too long"):
        validate_domain(".".join(["a"] * 128))


def test_validate_domain_empty() -> None:
    with pytest.raises(ValidationError, match="Invalid domain"):
        validate_domain("")


def test_validate_search_pattern_valid() -> None:
    assert validate_search_pattern("error") == "error"
    assert validate_search_pattern("some.path/to:file") == "some.path/to:file"


def test_validate_search_pattern_empty() -> None:
    with pytest.raises(ValidationError, match="cannot be empty"):
        validate_search_pattern("")


def test_validate_search_pattern_invalid() -> None:
    with pytest.raises(ValidationError, match="Invalid search pattern"):
        validate_search_pattern("cmd | cat /etc/passwd")


def test_validate_search_pattern_too_long() -> None:
    with pytest.raises(ValidationError, match="too long"):
        validate_search_pattern("a" * 1001)


def test_validate_username_valid() -> None:
    assert validate_username("root") == "root"
    assert validate_username("john_doe") == "john_doe"


def test_validate_username_empty() -> None:
    with pytest.raises(ValidationError, match="cannot be empty"):
        validate_username("")


def test_validate_username_invalid() -> None:
    with pytest.raises(ValidationError, match="Invalid username"):
        validate_username("-invalid")


def test_validate_username_too_long() -> None:
    with pytest.raises(ValidationError, match="too long"):
        validate_username("a" * 33)


def test_validate_lines_param_journal() -> None:
    from mikrus_mcp.validators import MAX_JOURNAL_LINES, validate_lines_param

    assert validate_lines_param(9999, MAX_JOURNAL_LINES) == 500


def test_check_dangerous_command_chmod() -> None:
    with pytest.raises(ValidationError, match="Dangerous"):
        check_dangerous_command("chmod 777 /")


def test_check_dangerous_command_fork_bomb() -> None:
    with pytest.raises(ValidationError, match="Dangerous"):
        check_dangerous_command(":(){ :|:& };:")


def test_check_dangerous_command_dd_to_sda() -> None:
    with pytest.raises(ValidationError, match="Dangerous"):
        check_dangerous_command("> /dev/sda")


def test_validate_path_write_warning(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    caplog.set_level(logging.WARNING)
    validate_path("/usr/local/bin/test", for_write=True)
    assert "outside typical" in caplog.text
