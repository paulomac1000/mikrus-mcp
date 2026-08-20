from __future__ import annotations

import inspect
from types import ModuleType
from typing import Any

import pytest

from mikrus_mcp import tool_mikrus, tool_system


MIKRUS_CASES = [
    ("describe_mikrus_capabilities", {}),
    ("list_configured_servers", {}),
    ("get_server_info", {}),
    ("list_servers", {}),
    ("get_server_stats", {}),
    ("restart_server", {}),
    ("get_logs", {}),
    ("get_log_by_id", {"log_id": "12345"}),
    ("boost_server", {}),
    ("get_db_info", {}),
    ("get_ports", {}),
    ("get_cloud", {}),
    ("assign_domain", {"port": "8080", "domain": "example.com"}),
]

SYSTEM_CASES = [
    ("read_file", {"path": "/tmp/example"}),
    ("write_file", {"path": "/tmp/example", "content": "content"}),
    ("get_service_status", {"name": "nginx"}),
    ("change_service_state", {"name": "nginx", "action": "restart"}),
    ("analyze_disk", {}),
    ("check_port", {"port": "8080"}),
    ("list_processes", {}),
    ("terminate_process", {"target": "123"}),
    ("update_system", {}),
    ("list_directory", {"path": "/tmp"}),
    ("tail_file", {"path": "/tmp/example"}),
    ("search_in_files", {"path": "/tmp", "pattern": "needle"}),
    ("get_memory_info", {}),
    ("get_network_info", {}),
    ("get_process_tree", {}),
    ("list_docker_containers", {}),
    ("get_docker_logs", {"container": "nginx"}),
    ("get_docker_stats", {}),
    ("get_journal_logs", {"unit": "nginx"}),
    ("find_system_errors", {}),
    ("search_journal_logs", {"term": "failure"}),
]

CASES = [
    *((tool_mikrus, name, arguments) for name, arguments in MIKRUS_CASES),
    *((tool_system, name, arguments) for name, arguments in SYSTEM_CASES),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module", "capability", "arguments"),
    CASES,
    ids=[name for _, name, _ in CASES],
)
async def test_tool_description_accessors_are_non_empty_and_name_capability(
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    capability: str,
    arguments: dict[str, Any],
) -> None:
    tool = getattr(module, capability)
    description = inspect.getdoc(tool)
    assert description

    async def fake_invoke(
        _ctx: object,
        invoked_capability: str,
        _arguments: dict[str, object],
    ) -> str:
        return f"{invoked_capability}: {description}"

    monkeypatch.setattr(module, "_invoke", fake_invoke)
    result = await tool(ctx=object(), **arguments)

    assert isinstance(result, str)
    assert result.strip()
    assert capability in result
