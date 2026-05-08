"""Smoke tests — verify response format compliance across all tools."""

import json

import pytest
import respx

from mikrus_mcp.client import MikrusClient
from mikrus_mcp.server import _call_tool_logic as call_tool

TOOLS_NO_PARAMS = [
    "get_server_info",
    "list_servers",
    "get_server_stats",
    "restart_server",
    "get_logs",
    "boost_server",
    "get_db_info",
    "get_ports",
    "get_cloud",
    "get_memory_info",
    "get_network_info",
    "get_process_tree",
    "list_docker_containers",
    "get_docker_stats",
    "update_system",
]

TOOLS_WITH_PARAMS = {
    "get_log_by_id": {"id": "1"},
    "assign_domain": {"port": "3000", "domain": "-"},
    "execute_command": {"cmd": "echo test"},
    "read_file": {"path": "/etc/hosts"},
    "write_file": {"path": "/tmp/x.txt", "content": "data"},
    "manage_service": {"name": "nginx", "action": "status"},
    "analyze_disk": {"path": "/"},
    "check_port": {"port": "80"},
    "manage_process": {"action": "list"},
    "list_directory": {"path": "/tmp"},
    "tail_file": {"path": "/var/log/syslog"},
    "search_in_files": {"path": "/etc", "pattern": "test"},
    "get_docker_logs": {"container": "app"},
    "get_journal_logs": {"unit": "ssh.service"},
    "find_system_errors": {"hours": 1},
    "search_journal_logs": {"term": "test"},
}


@pytest.mark.asyncio
async def test_all_tools_return_success_format() -> None:
    """Verify every tool returns {"success": True/False, ...} structure."""
    client = MikrusClient("https://api.mikr.us", "test-key", "test-srv")
    await client.open()

    with respx.mock:
        respx.post("https://api.mikr.us/info").respond(
            json={"server_id": "srv", "param_ram": "1024"}
        )
        respx.post("https://api.mikr.us/serwery").respond(json=[])
        respx.post("https://api.mikr.us/stats").respond(json={"uptime": "1d"})
        respx.post("https://api.mikr.us/restart").respond(text="OK")
        respx.post("https://api.mikr.us/logs").respond(json=[])
        respx.post("https://api.mikr.us/logs/1").respond(json={"id": "1"})
        respx.post("https://api.mikr.us/amfetamina").respond(json={"status": "ok"})
        respx.post("https://api.mikr.us/db").respond(json={"host": "db"})
        respx.post("https://api.mikr.us/porty").respond(json={"tcp": [], "udp": []})
        respx.post("https://api.mikr.us/cloud").respond(json={"services": []})
        respx.post("https://api.mikr.us/domain").respond(
            json={"domain": "test.mikr.us", "port": "3000"}
        )
        respx.post("https://api.mikr.us/exec").respond(
            json={"output": "test", "exit_code": 0}
        )

        for tool_name in TOOLS_NO_PARAMS:
            result = await call_tool(tool_name, {}, client=client)
            data = json.loads(result[0].text)
            assert "success" in data, f"Tool '{tool_name}' missing 'success' field"
            assert isinstance(data["success"], bool), (
                f"Tool '{tool_name}' success is not bool"
            )

        for tool_name, args in TOOLS_WITH_PARAMS.items():
            result = await call_tool(tool_name, args, client=client)
            data = json.loads(result[0].text)
            assert "success" in data, f"Tool '{tool_name}' missing 'success' field"
            assert isinstance(data["success"], bool), (
                f"Tool '{tool_name}' success is not bool"
            )

    await client.close()
