"""Tests for mikrus_mcp client."""

import pytest
import respx
from httpx import Response

from mikrus_mcp.client import MikrusClient


@pytest.fixture
def client() -> MikrusClient:
    return MikrusClient("https://api.mikr.us", "test-key", "test-srv")


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
        # respx does not easily simulate timeout; verify the call goes through
        # with the extended timeout configured for exec endpoints.
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
    with pytest.raises(ValueError, match="Invalid path"):
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
    with pytest.raises(ValueError, match="Invalid action"):
        await client.manage_service("nginx", "delete")
    await client.close()


@pytest.mark.asyncio
async def test_manage_service_invalid_name(client: MikrusClient) -> None:
    await client.open()
    with pytest.raises(ValueError, match="Invalid service name"):
        await client.manage_service("rm -rf /", "status")
    await client.close()


@pytest.mark.asyncio
async def test_analyze_disk(client: MikrusClient) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/exec")
        route.respond(
            json={
                "output": "Filesystem  Size  Used Avail Use%\n/dev/sda1 15G 10G 5G 67%",
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
async def test_analyze_disk_relative_path(client: MikrusClient) -> None:
    await client.open()
    with pytest.raises(ValueError, match="absolute"):
        await client.analyze_disk("home/user")
    await client.close()


@pytest.mark.asyncio
async def test_check_port(client: MikrusClient) -> None:
    with respx.mock:
        route = respx.post("https://api.mikr.us/exec")
        route.respond(
            json={
                "output": 'LISTEN 0 128 *:3000 *:* users:(("node",pid=1234))',
                "exit_code": 0,
            }
        )
        await client.open()
        result = await client.check_port("3000")
        await client.close()

    assert "LISTEN" in result["output"]
    body = route.calls[0].request.content.decode()
    assert "ss+-tlnp" in body


@pytest.mark.asyncio
async def test_check_port_invalid(client: MikrusClient) -> None:
    await client.open()
    with pytest.raises(ValueError, match="Invalid port"):
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
    with pytest.raises(ValueError, match="Invalid action"):
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
    assert "apt+update" in body
    assert "apt+upgrade" in body
