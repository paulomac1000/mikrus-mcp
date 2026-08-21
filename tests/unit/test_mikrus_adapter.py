from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from mikrus_mcp.clients.mikrus import MikrusClient
from mikrus_mcp.validators import ValidationError


async def call_exec(
    operation: Callable[[MikrusClient], Awaitable[Any]],
    *,
    output: str = "ok",
) -> tuple[Any, str]:
    observed_command = ""

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal observed_command
        assert request.url.path == "/exec"
        form = parse_qs(request.content.decode())
        assert form["srv"] == ["abc123"]
        assert form["key"] == ["test-key"]
        observed_command = form["cmd"][0]
        return httpx.Response(200, json={"output": output}, request=request)

    client = MikrusClient(
        "https://api.mikr.us",
        "test-key",
        "abc123",
        requests_per_minute=100_000,
        transport=httpx.MockTransport(handler),
    )
    async with client:
        result = await operation(client)
    return result, observed_command


EXEC_CASES: list[tuple[str, Callable[[MikrusClient], Awaitable[Any]], str]] = [
    ("read_file", lambda client: client.read_file("/tmp/example"), "head -n 200"),
    ("write_file", lambda client: client.write_file("/tmp/example", "value"), "python3 -c"),
    (
        "service_status",
        lambda client: client.get_service_status("nginx"),
        "systemctl status --no-pager -- nginx",
    ),
    (
        "service_restart",
        lambda client: client.change_service_state("nginx", "restart"),
        "systemctl restart -- nginx",
    ),
    ("analyze_disk", lambda client: client.analyze_disk("/var/log"), "df -h"),
    ("check_port", lambda client: client.check_port("443"), ":443 "),
    ("list_processes", lambda client: client.list_processes(), "ps aux --sort=-%mem"),
    ("terminate_pid", lambda client: client.terminate_process("123"), "kill -TERM -- 123"),
    (
        "terminate_name",
        lambda client: client.terminate_process("nginx"),
        "pkill -TERM -x -- nginx",
    ),
    ("update_system", lambda client: client.update_system(), "apt-get upgrade -y"),
    ("list_directory", lambda client: client.list_directory("/tmp"), "ls -la"),
    ("tail_file", lambda client: client.tail_file("/tmp/app.log", 20), "tail -n 20"),
    (
        "search_in_files",
        lambda client: client.search_in_files("/tmp", "needle"),
        "grep -r -F -n",
    ),
    ("memory", lambda client: client.get_memory_info(), "free -h"),
    ("network", lambda client: client.get_network_info(), "ip addr"),
    ("process_tree", lambda client: client.get_process_tree(), "ps auxf"),
    (
        "docker_logs",
        lambda client: client.get_docker_logs("nginx", 25),
        "docker logs --tail 25 -- nginx",
    ),
    (
        "journal_logs",
        lambda client: client.get_journal_logs("nginx", 30),
        "journalctl -u nginx -n 30",
    ),
    (
        "system_errors",
        lambda client: client.find_system_errors(2),
        "--since '2 hours ago'",
    ),
    (
        "search_journal",
        lambda client: client.search_journal_logs("failure", 40),
        "grep -i -F -- failure",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("_name", "operation", "expected_command"),
    EXEC_CASES,
    ids=[name for name, _, _ in EXEC_CASES],
)
async def test_exec_builders_send_expected_bounded_command(
    _name: str,
    operation: Callable[[MikrusClient], Awaitable[Any]],
    expected_command: str,
) -> None:
    result, command = await call_exec(operation)

    assert result == {"output": "ok"}
    assert expected_command in command


@pytest.mark.asyncio
async def test_change_service_state_rejects_read_only_action_before_http() -> None:
    client = MikrusClient("https://api.mikr.us", "test-key", "abc123")

    with pytest.raises(ValidationError, match="read-only service actions"):
        await client.change_service_state("nginx", "status")


@pytest.mark.asyncio
async def test_list_docker_containers_parses_jsonl_and_ignores_noise() -> None:
    output = "\n".join(
        [
            '{"ID":"abc","Names":"/nginx","Image":"nginx:1.27",'
            '"State":"running","Status":"Up 2 hours"}',
            "not-json",
            '["not", "a", "container"]',
        ]
    )
    result, command = await call_exec(lambda client: client.list_docker_containers(), output=output)

    assert command == "docker ps -a --format '{{json .}}'"
    assert result["containers"] == [
        {
            "ID": "abc",
            "Names": "/nginx",
            "Image": "nginx:1.27",
            "State": "running",
            "Status": "Up 2 hours",
        }
    ]


@pytest.mark.asyncio
async def test_get_docker_stats_parses_jsonl_snapshot() -> None:
    output = (
        '{"Container":"abc","Name":"nginx","CPUPerc":"0.10%",'
        '"MemUsage":"10MiB / 1GiB","MemPerc":"1.00%","NetIO":"1kB / 2kB",'
        '"BlockIO":"0B / 0B","PIDs":"5"}'
    )
    result, command = await call_exec(lambda client: client.get_docker_stats(), output=output)

    assert command == "docker stats --no-stream --format '{{json .}}'"
    assert result["containers"] == [
        {
            "Container": "abc",
            "Name": "nginx",
            "CPUPerc": "0.10%",
            "MemUsage": "10MiB / 1GiB",
            "MemPerc": "1.00%",
            "NetIO": "1kB / 2kB",
            "BlockIO": "0B / 0B",
            "PIDs": "5",
        }
    ]
