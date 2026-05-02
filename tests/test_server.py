"""Tests for MCP server handlers."""

import json

import pytest
import respx

from mikrus_mcp.client import MikrusClient
from mikrus_mcp.server import _call_tool_logic as call_tool


@pytest.fixture
def mock_client() -> MikrusClient:
    return MikrusClient("https://api.mikr.us", "key", "srv")


@pytest.mark.asyncio
async def test_get_server_info(mock_client: MikrusClient) -> None:
    with respx.mock:
        respx.post("https://api.mikr.us/info").respond(
            json={"server_id": "srv", "param_ram": "1024"}
        )
        await mock_client.open()
        result = await call_tool("get_server_info", {}, client=mock_client)
        await mock_client.close()

    assert len(result) == 1
    assert result[0].type == "text"
    data = json.loads(result[0].text)
    assert data["server_id"] == "srv"


@pytest.mark.asyncio
async def test_get_server_stats(mock_client: MikrusClient) -> None:
    with respx.mock:
        respx.post("https://api.mikr.us/stats").respond(json={"uptime": "5 days"})
        await mock_client.open()
        result = await call_tool("get_server_stats", {}, client=mock_client)
        await mock_client.close()

    data = json.loads(result[0].text)
    assert data["uptime"] == "5 days"


@pytest.mark.asyncio
async def test_execute_command(mock_client: MikrusClient) -> None:
    with respx.mock:
        respx.post("https://api.mikr.us/exec").respond(json={"output": "hello", "exit_code": 0})
        await mock_client.open()
        result = await call_tool("execute_command", {"cmd": "echo hello"}, client=mock_client)
        await mock_client.close()

    data = json.loads(result[0].text)
    assert data["output"] == "hello"


@pytest.mark.asyncio
async def test_execute_command_missing_param(mock_client: MikrusClient) -> None:
    await mock_client.open()
    result = await call_tool("execute_command", {}, client=mock_client)
    await mock_client.close()

    assert "Error:" in result[0].text
    assert "cmd" in result[0].text


@pytest.mark.asyncio
async def test_restart_server(mock_client: MikrusClient) -> None:
    with respx.mock:
        respx.post("https://api.mikr.us/restart").respond(text="OK")
        await mock_client.open()
        result = await call_tool("restart_server", {}, client=mock_client)
        await mock_client.close()

    data = json.loads(result[0].text)
    assert data["raw"] == "OK"


@pytest.mark.asyncio
async def test_get_logs(mock_client: MikrusClient) -> None:
    with respx.mock:
        respx.post("https://api.mikr.us/logs").respond(json=[{"id": "1"}])
        await mock_client.open()
        result = await call_tool("get_logs", {}, client=mock_client)
        await mock_client.close()

    data = json.loads(result[0].text)
    assert data[0]["id"] == "1"


@pytest.mark.asyncio
async def test_get_log_by_id(mock_client: MikrusClient) -> None:
    with respx.mock:
        respx.post("https://api.mikr.us/logs/5").respond(json={"id": "5", "task": "restart"})
        await mock_client.open()
        result = await call_tool("get_log_by_id", {"id": "5"}, client=mock_client)
        await mock_client.close()

    data = json.loads(result[0].text)
    assert data["id"] == "5"


@pytest.mark.asyncio
async def test_get_log_by_id_missing_param(mock_client: MikrusClient) -> None:
    await mock_client.open()
    result = await call_tool("get_log_by_id", {}, client=mock_client)
    await mock_client.close()

    assert "Error:" in result[0].text


@pytest.mark.asyncio
async def test_boost_server(mock_client: MikrusClient) -> None:
    with respx.mock:
        respx.post("https://api.mikr.us/amfetamina").respond(json={"status": "ok"})
        await mock_client.open()
        result = await call_tool("boost_server", {}, client=mock_client)
        await mock_client.close()

    data = json.loads(result[0].text)
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_unknown_tool(mock_client: MikrusClient) -> None:
    await mock_client.open()
    result = await call_tool("unknown_tool", {}, client=mock_client)
    await mock_client.close()

    assert "Error:" in result[0].text
    assert "Unknown tool" in result[0].text


@pytest.mark.asyncio
async def test_api_error(mock_client: MikrusClient) -> None:
    with respx.mock:
        respx.post("https://api.mikr.us/info").respond(status_code=500, text="Boom")
        await mock_client.open()
        result = await call_tool("get_server_info", {}, client=mock_client)
        await mock_client.close()

    assert "Error:" in result[0].text
    assert "HTTP 500" in result[0].text


@pytest.mark.asyncio
async def test_list_servers(mock_client: MikrusClient) -> None:
    with respx.mock:
        respx.post("https://api.mikr.us/serwery").respond(json=[{"server_id": "srv1"}])
        await mock_client.open()
        result = await call_tool("list_servers", {}, client=mock_client)
        await mock_client.close()

    data = json.loads(result[0].text)
    assert data[0]["server_id"] == "srv1"


@pytest.mark.asyncio
async def test_get_db_info(mock_client: MikrusClient) -> None:
    with respx.mock:
        respx.post("https://api.mikr.us/db").respond(json={"host": "db.mikr.us", "user": "admin"})
        await mock_client.open()
        result = await call_tool("get_db_info", {}, client=mock_client)
        await mock_client.close()

    data = json.loads(result[0].text)
    assert data["host"] == "db.mikr.us"


@pytest.mark.asyncio
async def test_get_ports(mock_client: MikrusClient) -> None:
    with respx.mock:
        respx.post("https://api.mikr.us/porty").respond(json={"tcp": ["22", "80"], "udp": ["53"]})
        await mock_client.open()
        result = await call_tool("get_ports", {}, client=mock_client)
        await mock_client.close()

    data = json.loads(result[0].text)
    assert "22" in data["tcp"]


@pytest.mark.asyncio
async def test_get_cloud(mock_client: MikrusClient) -> None:
    with respx.mock:
        respx.post("https://api.mikr.us/cloud").respond(json={"services": [{"name": "backup"}]})
        await mock_client.open()
        result = await call_tool("get_cloud", {}, client=mock_client)
        await mock_client.close()

    data = json.loads(result[0].text)
    assert data["services"][0]["name"] == "backup"


@pytest.mark.asyncio
async def test_assign_domain(mock_client: MikrusClient) -> None:
    with respx.mock:
        respx.post("https://api.mikr.us/domain").respond(
            json={"domain": "app.mikr.us", "port": "3000"}
        )
        await mock_client.open()
        result = await call_tool(
            "assign_domain", {"port": "3000", "domain": "-"}, client=mock_client
        )
        await mock_client.close()

    data = json.loads(result[0].text)
    assert data["domain"] == "app.mikr.us"


@pytest.mark.asyncio
async def test_assign_domain_missing_params(mock_client: MikrusClient) -> None:
    await mock_client.open()
    result = await call_tool("assign_domain", {}, client=mock_client)
    await mock_client.close()

    assert "Error:" in result[0].text
    assert "port" in result[0].text


@pytest.mark.asyncio
async def test_read_file(mock_client: MikrusClient) -> None:
    with respx.mock:
        respx.post("https://api.mikr.us/exec").respond(
            json={"output": "127.0.0.1 localhost", "exit_code": 0}
        )
        await mock_client.open()
        result = await call_tool("read_file", {"path": "/etc/hosts"}, client=mock_client)
        await mock_client.close()

    data = json.loads(result[0].text)
    assert "localhost" in data["output"]


@pytest.mark.asyncio
async def test_read_file_missing_path(mock_client: MikrusClient) -> None:
    await mock_client.open()
    result = await call_tool("read_file", {}, client=mock_client)
    await mock_client.close()

    assert "Error:" in result[0].text


@pytest.mark.asyncio
async def test_write_file(mock_client: MikrusClient) -> None:
    with respx.mock:
        respx.post("https://api.mikr.us/exec").respond(
            json={"output": "WRITE_OK\n", "exit_code": 0}
        )
        await mock_client.open()
        result = await call_tool(
            "write_file", {"path": "/tmp/x.txt", "content": "data"}, client=mock_client
        )
        await mock_client.close()

    data = json.loads(result[0].text)
    assert "WRITE_OK" in data["output"]


@pytest.mark.asyncio
async def test_manage_service(mock_client: MikrusClient) -> None:
    with respx.mock:
        respx.post("https://api.mikr.us/exec").respond(
            json={"output": "active (running)", "exit_code": 0}
        )
        await mock_client.open()
        result = await call_tool(
            "manage_service", {"name": "nginx", "action": "status"}, client=mock_client
        )
        await mock_client.close()

    data = json.loads(result[0].text)
    assert "active" in data["output"]


@pytest.mark.asyncio
async def test_analyze_disk(mock_client: MikrusClient) -> None:
    with respx.mock:
        respx.post("https://api.mikr.us/exec").respond(
            json={"output": "/dev/sda1 15G 10G 5G 67%", "exit_code": 0}
        )
        await mock_client.open()
        result = await call_tool("analyze_disk", {"path": "/"}, client=mock_client)
        await mock_client.close()

    data = json.loads(result[0].text)
    assert "67%" in data["output"]


@pytest.mark.asyncio
async def test_check_port(mock_client: MikrusClient) -> None:
    with respx.mock:
        respx.post("https://api.mikr.us/exec").respond(
            json={"output": "LISTEN *:80", "exit_code": 0}
        )
        await mock_client.open()
        result = await call_tool("check_port", {"port": "80"}, client=mock_client)
        await mock_client.close()

    data = json.loads(result[0].text)
    assert "LISTEN" in data["output"]


@pytest.mark.asyncio
async def test_check_port_missing(mock_client: MikrusClient) -> None:
    await mock_client.open()
    result = await call_tool("check_port", {}, client=mock_client)
    await mock_client.close()

    assert "Error:" in result[0].text


@pytest.mark.asyncio
async def test_manage_process_list(mock_client: MikrusClient) -> None:
    with respx.mock:
        respx.post("https://api.mikr.us/exec").respond(
            json={"output": "root 1234 node", "exit_code": 0}
        )
        await mock_client.open()
        result = await call_tool("manage_process", {"action": "list"}, client=mock_client)
        await mock_client.close()

    data = json.loads(result[0].text)
    assert "node" in data["output"]


@pytest.mark.asyncio
async def test_manage_process_missing_action(mock_client: MikrusClient) -> None:
    await mock_client.open()
    result = await call_tool("manage_process", {}, client=mock_client)
    await mock_client.close()

    assert "Error:" in result[0].text


@pytest.mark.asyncio
async def test_update_system(mock_client: MikrusClient) -> None:
    with respx.mock:
        respx.post("https://api.mikr.us/exec").respond(
            json={"output": "0 upgraded, 0 newly installed", "exit_code": 0}
        )
        await mock_client.open()
        result = await call_tool("update_system", {}, client=mock_client)
        await mock_client.close()

    data = json.loads(result[0].text)
    assert "upgraded" in data["output"]


@pytest.mark.asyncio
async def test_list_directory(mock_client: MikrusClient) -> None:
    with respx.mock:
        respx.post("https://api.mikr.us/exec").respond(
            json={"output": "drwxr-xr-x root /tmp", "exit_code": 0}
        )
        await mock_client.open()
        result = await call_tool("list_directory", {"path": "/tmp"}, client=mock_client)
        await mock_client.close()

    data = json.loads(result[0].text)
    assert "root" in data["output"]


@pytest.mark.asyncio
async def test_tail_file(mock_client: MikrusClient) -> None:
    with respx.mock:
        respx.post("https://api.mikr.us/exec").respond(
            json={"output": "tail output", "exit_code": 0}
        )
        await mock_client.open()
        result = await call_tool(
            "tail_file", {"path": "/var/log/syslog", "lines": 20}, client=mock_client
        )
        await mock_client.close()

    data = json.loads(result[0].text)
    assert "tail output" in data["output"]


@pytest.mark.asyncio
async def test_search_in_files(mock_client: MikrusClient) -> None:
    with respx.mock:
        respx.post("https://api.mikr.us/exec").respond(
            json={"output": "/etc/hosts:1:127.0.0.1", "exit_code": 0}
        )
        await mock_client.open()
        result = await call_tool(
            "search_in_files", {"path": "/etc", "pattern": "127.0"}, client=mock_client
        )
        await mock_client.close()

    data = json.loads(result[0].text)
    assert "127.0" in data["output"]


@pytest.mark.asyncio
async def test_get_memory_info(mock_client: MikrusClient) -> None:
    with respx.mock:
        respx.post("https://api.mikr.us/exec").respond(json={"output": "Mem: 1G", "exit_code": 0})
        await mock_client.open()
        result = await call_tool("get_memory_info", {}, client=mock_client)
        await mock_client.close()

    data = json.loads(result[0].text)
    assert "Mem" in data["output"]


@pytest.mark.asyncio
async def test_get_network_info(mock_client: MikrusClient) -> None:
    with respx.mock:
        respx.post("https://api.mikr.us/exec").respond(json={"output": "eth0: UP", "exit_code": 0})
        await mock_client.open()
        result = await call_tool("get_network_info", {}, client=mock_client)
        await mock_client.close()

    data = json.loads(result[0].text)
    assert "eth0" in data["output"]


@pytest.mark.asyncio
async def test_get_process_tree(mock_client: MikrusClient) -> None:
    with respx.mock:
        respx.post("https://api.mikr.us/exec").respond(
            json={"output": "root 1 init", "exit_code": 0}
        )
        await mock_client.open()
        result = await call_tool("get_process_tree", {}, client=mock_client)
        await mock_client.close()

    data = json.loads(result[0].text)
    assert "init" in data["output"]


@pytest.mark.asyncio
async def test_list_docker_containers(mock_client: MikrusClient) -> None:
    with respx.mock:
        respx.post("https://api.mikr.us/exec").respond(
            json={"output": '[{"Names":"app"}]', "exit_code": 0}
        )
        await mock_client.open()
        result = await call_tool("list_docker_containers", {}, client=mock_client)
        await mock_client.close()

    data = json.loads(result[0].text)
    assert "app" in data["output"]


@pytest.mark.asyncio
async def test_get_docker_logs(mock_client: MikrusClient) -> None:
    with respx.mock:
        respx.post("https://api.mikr.us/exec").respond(
            json={"output": "docker log line", "exit_code": 0}
        )
        await mock_client.open()
        result = await call_tool(
            "get_docker_logs", {"container": "app", "lines": 10}, client=mock_client
        )
        await mock_client.close()

    data = json.loads(result[0].text)
    assert "docker log line" in data["output"]


@pytest.mark.asyncio
async def test_get_docker_stats(mock_client: MikrusClient) -> None:
    with respx.mock:
        respx.post("https://api.mikr.us/exec").respond(
            json={"output": '{"CPUPerc":"10%"}', "exit_code": 0}
        )
        await mock_client.open()
        result = await call_tool("get_docker_stats", {}, client=mock_client)
        await mock_client.close()

    data = json.loads(result[0].text)
    assert "10%" in data["output"]


@pytest.mark.asyncio
async def test_get_journal_logs(mock_client: MikrusClient) -> None:
    with respx.mock:
        respx.post("https://api.mikr.us/exec").respond(
            json={"output": "journal line", "exit_code": 0}
        )
        await mock_client.open()
        result = await call_tool(
            "get_journal_logs", {"unit": "ssh.service", "lines": 5}, client=mock_client
        )
        await mock_client.close()

    data = json.loads(result[0].text)
    assert "journal line" in data["output"]


@pytest.mark.asyncio
async def test_find_system_errors(mock_client: MikrusClient) -> None:
    with respx.mock:
        respx.post("https://api.mikr.us/exec").respond(
            json={"output": "error found", "exit_code": 0}
        )
        await mock_client.open()
        result = await call_tool("find_system_errors", {"hours": 2}, client=mock_client)
        await mock_client.close()

    data = json.loads(result[0].text)
    assert "error found" in data["output"]


@pytest.mark.asyncio
async def test_search_journal_logs(mock_client: MikrusClient) -> None:
    with respx.mock:
        respx.post("https://api.mikr.us/exec").respond(json={"output": "matched", "exit_code": 0})
        await mock_client.open()
        result = await call_tool(
            "search_journal_logs", {"term": "fail", "lines": 10}, client=mock_client
        )
        await mock_client.close()

    data = json.loads(result[0].text)
    assert "matched" in data["output"]
