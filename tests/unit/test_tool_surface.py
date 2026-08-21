"""End-to-end application-surface coverage over realistic mikr.us response shapes.

Exercises every registered capability through the invocation kernel using a mock
backend whose payloads mirror the real mikr.us API responses, and calls the public
tool callables themselves so the thin MCP wrappers stay covered.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from mikrus_mcp.approvals import ApprovalRegistry, normalized_arguments_digest
from mikrus_mcp.config import Settings, TargetConfig
from mikrus_mcp.kernel import CallerContext, InvocationKernel
from mikrus_mcp.targets import TargetRegistry

INFO_PAYLOAD: dict[str, object] = {
    "server_id": "abc123",
    "imie_id": "abc123",
    "server_name": None,
    "expires": "2027-02-13 00:00:00",
    "expires_storage": None,
    "param_ram": "1024",
    "param_disk": "15",
    "lastlog_panel": "2026-07-08 00:21:18",
    "mikrus_pro": "nie",
}

SERVERS_PAYLOAD: list[dict[str, object]] = [
    {
        "server_id": "abc123",
        "server_name": "mybox",
        "expires": "2027-02-13 00:00:00",
        "param_ram": "1024",
        "param_disk": "15",
    }
]

STATS_PAYLOAD: dict[str, object] = {
    "free": (
        "               total        used        free      shared  buff/cache   available\n"
        "Mem:           976Mi       412Mi       102Mi        12Mi       461Mi       402Mi\n"
        "Swap:             0B          0B          0B"
    ),
    "df": (
        "Filesystem      Size  Used Avail Use% Mounted on\n/dev/vda1        15G  4.2G  9.7G  31% /"
    ),
    "uptime": " 14:23:01 up 5 days,  3:21,  1 user,  load average: 0.08, 0.02, 0.01",
    "ps": (
        "USER       PID %CPU %MEM    VSZ   RSS TTY      STAT START   TIME COMMAND\n"
        "root         1  0.0  0.3 167404 11084 ?        Ss   Aug15   0:02 /sbin/init"
    ),
}

LOGS_PAYLOAD: list[dict[str, object]] = [
    {
        "id": 12345,
        "server_id": "abc123",
        "task": "restart",
        "when_created": "2026-08-19 10:00:00",
        "when_done": "2026-08-19 10:00:42",
        "output": "ok",
    }
]

DB_PAYLOAD: dict[str, object] = {
    "user": "mikrus_abc123",
    "host": "db.mikr.us",
    "port": "3306",
    "name": "mikrus_abc123",
    "password": "redacted-secret",
}

DOCKER_PS_JSONL = "\n".join(
    [
        '{"Command":"\\"/docker-entrypoint.…\\"","CreatedAt":"2026-08-19 10:00:00 +0000 UTC",'
        '"ID":"a1b2c3d4e5f6","Image":"nginx:1.27","Labels":"","LocalVolumes":"0","Mounts":"",'
        '"Names":"nginx","Networks":"bridge","Ports":"80/tcp","RunningFor":"2 hours ago",'
        '"Size":"0B","State":"running","Status":"Up 2 hours"}',
        "not-json-noise-line",
        '{"BlockIO":"0B / 0B","CPUPerc":"0.12%","Container":"nginx","ID":"a1b2c3d4e5f6",'
        '"MemPerc":"1.23%","MemUsage":"24.5MiB / 512MiB","Name":"nginx",'
        '"NetIO":"1.2kB / 3.4kB","PIDs":"3"}',
    ]
)


class RealisticMikrusClient:
    """Backend double returning real mikr.us API response shapes with generic values."""

    def __init__(self, config: TargetConfig) -> None:
        self.stable_identity = config.stable_identity
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    def _track(self, name: str, *args: Any) -> None:
        self.calls.append((name, args))

    @staticmethod
    def _docker_result() -> dict[str, object]:
        containers = [
            json.loads(line) for line in DOCKER_PS_JSONL.splitlines() if line.startswith("{")
        ]
        return {"output": DOCKER_PS_JSONL, "containers": containers}

    async def get_server_info(self) -> dict[str, object]:
        self._track("get_server_info")
        return INFO_PAYLOAD

    async def list_servers(self) -> list[dict[str, object]]:
        self._track("list_servers")
        return SERVERS_PAYLOAD

    async def get_server_stats(self) -> dict[str, object]:
        self._track("get_server_stats")
        return STATS_PAYLOAD

    async def get_logs(self) -> list[dict[str, object]]:
        self._track("get_logs")
        return LOGS_PAYLOAD

    async def get_log_by_id(self, log_id: str) -> dict[str, object]:
        self._track("get_log_by_id", log_id)
        return LOGS_PAYLOAD[0]

    async def get_db_info(self) -> dict[str, object]:
        self._track("get_db_info")
        return DB_PAYLOAD

    async def get_ports(self) -> list[int]:
        self._track("get_ports")
        return [20359, 30359]

    async def get_cloud(self) -> list[dict[str, object]]:
        self._track("get_cloud")
        return []

    async def restart_server(self) -> dict[str, object]:
        self._track("restart_server")
        return {"status": "ok"}

    async def boost_server(self) -> dict[str, object]:
        self._track("boost_server")
        return {"status": "ok"}

    async def assign_domain(self, port: str, domain: str) -> dict[str, object]:
        self._track("assign_domain", port, domain)
        return {"status": "ok", "domain": domain}

    async def read_file(self, path: str) -> dict[str, object]:
        self._track("read_file", path)
        return {"output": "line one\nline two\n"}

    async def write_file(self, path: str, content: str) -> dict[str, object]:
        self._track("write_file", path, content)
        return {"output": ""}

    async def get_service_status(self, name: str) -> dict[str, object]:
        self._track("get_service_status", name)
        return {"output": f"● {name}.service - loaded active running"}

    async def change_service_state(self, name: str, action: str) -> dict[str, object]:
        self._track("change_service_state", name, action)
        return {"output": ""}

    async def analyze_disk(self, path: str = "/") -> dict[str, object]:
        self._track("analyze_disk", path)
        return {"output": STATS_PAYLOAD["df"]}

    async def check_port(self, port: str) -> dict[str, object]:
        self._track("check_port", port)
        return {"output": f"LISTEN 0.0.0.0:{port}"}

    async def list_processes(self) -> dict[str, object]:
        self._track("list_processes")
        return {"output": str(STATS_PAYLOAD["ps"])}

    async def terminate_process(self, target: str) -> dict[str, object]:
        self._track("terminate_process", target)
        return {"output": ""}

    async def update_system(self) -> dict[str, object]:
        self._track("update_system")
        return {"output": "Reading package lists... Done"}

    async def list_directory(self, path: str) -> dict[str, object]:
        self._track("list_directory", path)
        return {"output": "total 8\ndrwxr-xr-x 2 root root 4096 Aug 19 10:00 ."}

    async def tail_file(self, path: str, lines: int = 50) -> dict[str, object]:
        self._track("tail_file", path, lines)
        return {"output": "final line"}

    async def search_in_files(self, path: str, pattern: str) -> dict[str, object]:
        self._track("search_in_files", path, pattern)
        return {"output": f"{path}/app.py:42: {pattern}"}

    async def get_memory_info(self) -> dict[str, object]:
        self._track("get_memory_info")
        return {"output": str(STATS_PAYLOAD["free"])}

    async def get_network_info(self) -> dict[str, object]:
        self._track("get_network_info")
        return {"output": "1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536"}

    async def get_process_tree(self) -> dict[str, object]:
        self._track("get_process_tree")
        return {"output": str(STATS_PAYLOAD["ps"])}

    async def list_docker_containers(self) -> dict[str, object]:
        self._track("list_docker_containers")
        return self._docker_result()

    async def get_docker_logs(self, container: str, lines: int = 50) -> dict[str, object]:
        self._track("get_docker_logs", container, lines)
        return {"output": "2026-08-19T10:00:00Z GET / 200"}

    async def get_docker_stats(self) -> dict[str, object]:
        self._track("get_docker_stats")
        return self._docker_result()

    async def get_journal_logs(self, unit: str, lines: int = 50) -> dict[str, object]:
        self._track("get_journal_logs", unit, lines)
        return {"output": "Aug 19 10:00:00 mybox systemd[1]: Started " + unit}

    async def find_system_errors(self, hours: int = 1) -> dict[str, object]:
        self._track("find_system_errors", hours)
        return {"output": "-- No entries --"}

    async def search_journal_logs(self, term: str, lines: int = 50) -> dict[str, object]:
        self._track("search_journal_logs", term, lines)
        return {"output": f"Aug 19 10:00:00 mybox app[999]: {term}"}


READ_TOOLS: list[tuple[str, dict[str, Any]]] = [
    ("describe_mikrus_capabilities", {}),
    ("list_configured_servers", {}),
    ("get_server_info", {}),
    ("list_servers", {}),
    ("get_server_stats", {}),
    ("get_logs", {}),
    ("get_log_by_id", {"log_id": "12345"}),
    ("get_db_info", {}),
    ("get_ports", {}),
    ("get_cloud", {}),
    ("read_file", {"path": "/var/log/app.log"}),
    ("get_service_status", {"name": "nginx"}),
    ("analyze_disk", {"path": "/var"}),
    ("check_port", {"port": "22"}),
    ("list_processes", {}),
    ("list_directory", {"path": "/etc"}),
    ("tail_file", {"path": "/var/log/app.log", "lines": 10}),
    ("search_in_files", {"path": "/etc", "pattern": "timeout"}),
    ("get_memory_info", {}),
    ("get_network_info", {}),
    ("get_process_tree", {}),
    ("list_docker_containers", {}),
    ("get_docker_logs", {"container": "nginx", "lines": 20}),
    ("get_docker_stats", {}),
    ("get_journal_logs", {"unit": "sshd", "lines": 20}),
    ("find_system_errors", {"hours": 2}),
    ("search_journal_logs", {"term": "failed", "lines": 10}),
]

MUTATION_TOOLS: list[tuple[str, dict[str, Any], str]] = [
    ("write_file", {"path": "/tmp/probe.txt", "content": "data"}, "/tmp/probe.txt"),
    ("change_service_state", {"name": "nginx", "action": "restart"}, "nginx"),
    ("terminate_process", {"target": "1234"}, "1234"),
    ("update_system", {}, "<target>"),
    ("restart_server", {}, "<target>"),
    ("boost_server", {}, "<target>"),
    ("assign_domain", {"port": "80", "domain": "example.com"}, "example.com"),
]


def make_kernel(write_enabled: bool, client: RealisticMikrusClient) -> InvocationKernel:
    target = TargetConfig(
        "prod", "mikrus", api_url="https://api.mikr.us", api_key="k", server_id="abc123"
    )
    settings = Settings(
        {"prod": target},
        "prod",
        write_enabled=write_enabled,
        allowed_scopes=frozenset(
            {"tool:*", "target:*", "target-id:*", "resource:*", "data:*", "write:server"}
        ),
    )
    registry = TargetRegistry({"prod": target}, factory=lambda _: client)  # type: ignore[arg-type]
    return InvocationKernel(
        settings,
        registry=registry,
        approvals=ApprovalRegistry(),  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "arguments"), READ_TOOLS)
async def test_read_tool_succeeds_with_realistic_payload(
    name: str, arguments: dict[str, Any]
) -> None:
    kernel = make_kernel(
        write_enabled=False,
        client=RealisticMikrusClient(
            TargetConfig(
                "prod", "mikrus", api_url="https://api.mikr.us", api_key="k", server_id="abc123"
            )
        ),
    )
    caller = CallerContext("principal", kernel.settings.allowed_scopes)
    try:
        result = await kernel.invoke(name, arguments, caller)
        assert result["success"] is True, result.get("error")
        assert result["data"] is not None
    finally:
        await kernel.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "arguments", "resource"), MUTATION_TOOLS)
async def test_mutation_tool_succeeds_after_bound_approval(
    name: str, arguments: dict[str, Any], resource: str
) -> None:
    target = TargetConfig(
        "prod", "mikrus", api_url="https://api.mikr.us", api_key="k", server_id="abc123"
    )
    client = RealisticMikrusClient(target)
    kernel = make_kernel(write_enabled=True, client=client)
    caller = CallerContext("principal", kernel.settings.allowed_scopes)
    kernel.approvals.issue_for_test(
        name,
        "principal",
        target.stable_identity,
        resource,
        normalized_arguments_digest(arguments),
    )
    try:
        result = await kernel.invoke(name, arguments, caller)
        assert result["success"] is True, result.get("error")
        assert client.calls[-1][0] == name
    finally:
        await kernel.close()


def _fake_ctx(kernel: InvocationKernel) -> Any:
    lifespan = SimpleNamespace(settings=kernel.settings, kernel=kernel)
    return SimpleNamespace(request_context=SimpleNamespace(lifespan_context=lifespan))


@pytest.mark.asyncio
async def test_public_tool_callables_delegate_to_kernel() -> None:
    from mikrus_mcp import tool_mikrus, tool_system

    target = TargetConfig(
        "prod", "mikrus", api_url="https://api.mikr.us", api_key="k", server_id="abc123"
    )
    kernel = make_kernel(write_enabled=True, client=RealisticMikrusClient(target))
    ctx = _fake_ctx(kernel)
    try:
        info = await tool_mikrus.get_server_info(ctx)
        assert info["success"] is True
        assert info["data"]["server_id"] == "abc123"

        described = await tool_mikrus.describe_mikrus_capabilities(ctx)
        assert described["data"]["supported_transports"] == ["stdio", "streamable-http"]

        listed = await tool_mikrus.list_configured_servers(ctx)
        assert listed["success"] is True

        stats = await tool_mikrus.get_server_stats(ctx)
        assert stats["data"]["free"].startswith("               total")

        ports = await tool_mikrus.get_ports(ctx)
        assert ports["data"] == [20359, 30359]

        read = await tool_system.read_file("/var/log/app.log", ctx)
        assert read["data"]["output"] == "line one\nline two\n"

        docker = await tool_system.list_docker_containers(ctx)
        assert len(docker["data"]["containers"]) == 2
    finally:
        await kernel.close()
