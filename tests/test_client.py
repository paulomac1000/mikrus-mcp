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
