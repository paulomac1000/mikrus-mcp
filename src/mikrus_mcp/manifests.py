"""Application-owned capability manifests and active-catalog rules."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from mikrus_mcp.config import Settings

SideEffects = Literal["read", "write", "destructive"]
Confidentiality = Literal["public", "internal", "personal", "sensitive", "credential"]


@dataclass(frozen=True, slots=True)
class CapabilityManifest:
    name: str
    version: str
    side_effects: SideEffects
    confidentiality: Confidentiality
    operational_impact: str
    cost: str
    reversible: bool
    idempotent: bool
    idempotency_mechanism: str | None
    retryable: bool
    retry_conditions: tuple[str, ...]
    concurrent_safe: bool
    concurrency_scope: str
    timeout_ms: int
    requires_approval: bool
    required_scopes: tuple[str, ...]
    target_binding: str
    target_required: bool = True
    resource_argument: str | None = None
    command_profile: bool = False

    def as_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["risk"] = self.risk
        return value

    @property
    def risk(self) -> str:
        if self.confidentiality in {"sensitive", "credential"} and self.side_effects == "read":
            return "SENSITIVE"
        return {
            "read": "READ",
            "write": "WRITE",
            "destructive": "DESTRUCTIVE",
        }[self.side_effects]


def _read(
    name: str,
    confidentiality: Confidentiality = "internal",
    *,
    timeout_ms: int = 10_000,
    target_required: bool = True,
    resource_argument: str | None = None,
) -> CapabilityManifest:
    return CapabilityManifest(
        name=name,
        version="2.0.0",
        side_effects="read",
        confidentiality=confidentiality,
        operational_impact="none",
        cost="cheap",
        reversible=True,
        idempotent=True,
        idempotency_mechanism="natural read",
        retryable=True,
        retry_conditions=("rate-limit", "transient-upstream"),
        concurrent_safe=True,
        concurrency_scope="none",
        timeout_ms=timeout_ms,
        requires_approval=False,
        required_scopes=(f"tool:{name}",),
        target_binding="configured immutable target identity",
        target_required=target_required,
        resource_argument=resource_argument,
    )


def _mutation(
    name: str,
    *,
    destructive: bool = False,
    impact: str = "persistent",
    timeout_ms: int = 30_000,
    resource_argument: str | None = None,
    command_profile: bool = False,
) -> CapabilityManifest:
    return CapabilityManifest(
        name=name,
        version="2.0.0",
        side_effects="destructive" if destructive else "write",
        confidentiality="internal",
        operational_impact=impact,
        cost="moderate",
        reversible=False,
        idempotent=False,
        idempotency_mechanism=None,
        retryable=False,
        retry_conditions=(),
        concurrent_safe=False,
        concurrency_scope="target-resource",
        timeout_ms=timeout_ms,
        requires_approval=True,
        required_scopes=(f"tool:{name}", "write:server"),
        target_binding="configured immutable target identity plus approval-bound resource",
        resource_argument=resource_argument,
        command_profile=command_profile,
    )


MANIFESTS: dict[str, CapabilityManifest] = {
    "get_server_info": _read("get_server_info"),
    "list_servers": _read("list_servers", "personal"),
    "get_server_stats": _read("get_server_stats"),
    "restart_server": _mutation(
        "restart_server", destructive=True, impact="outage", timeout_ms=120_000
    ),
    "get_logs": _read("get_logs", "sensitive"),
    "get_log_by_id": _read("get_log_by_id", "sensitive", resource_argument="log_id"),
    "boost_server": _mutation("boost_server", impact="transient"),
    "get_db_info": _read("get_db_info", "credential"),
    "get_ports": _read("get_ports"),
    "get_cloud": _read("get_cloud", "personal"),
    "assign_domain": _mutation("assign_domain", resource_argument="domain"),
    "execute_command": _mutation(
        "execute_command",
        destructive=True,
        impact="outage",
        timeout_ms=60_000,
        resource_argument="cmd",
        command_profile=True,
    ),
    "read_file": _read("read_file", "sensitive", resource_argument="path"),
    "write_file": _mutation("write_file", resource_argument="path"),
    "get_service_status": _read(
        "get_service_status", resource_argument="name"
    ),
    "change_service_state": _mutation(
        "change_service_state", destructive=True, impact="outage", resource_argument="name"
    ),
    "analyze_disk": _read("analyze_disk", timeout_ms=30_000, resource_argument="path"),
    "check_port": _read("check_port", resource_argument="port"),
    "list_processes": _read("list_processes", "sensitive"),
    "terminate_process": _mutation(
        "terminate_process", destructive=True, impact="outage", resource_argument="target"
    ),
    "update_system": _mutation(
        "update_system", destructive=True, impact="outage", timeout_ms=120_000
    ),
    "list_directory": _read("list_directory", "sensitive", resource_argument="path"),
    "tail_file": _read("tail_file", "sensitive", resource_argument="path"),
    "search_in_files": _read(
        "search_in_files", "sensitive", timeout_ms=30_000, resource_argument="path"
    ),
    "get_memory_info": _read("get_memory_info"),
    "get_network_info": _read("get_network_info", "sensitive"),
    "get_process_tree": _read("get_process_tree", "sensitive"),
    "list_docker_containers": _read("list_docker_containers", "sensitive"),
    "get_docker_logs": _read(
        "get_docker_logs", "sensitive", resource_argument="container"
    ),
    "get_docker_stats": _read("get_docker_stats"),
    "get_journal_logs": _read(
        "get_journal_logs", "sensitive", resource_argument="unit"
    ),
    "find_system_errors": _read("find_system_errors", "sensitive"),
    "search_journal_logs": _read("search_journal_logs", "sensitive"),
    "list_configured_servers": _read(
        "list_configured_servers", "sensitive", timeout_ms=1_000, target_required=False
    ),
    "describe_mikrus_capabilities": _read(
        "describe_mikrus_capabilities", "public", timeout_ms=1_000, target_required=False
    ),
}


def active_names(settings: Settings) -> set[str]:
    names = set(MANIFESTS)
    if not settings.command_execution_enabled:
        names.remove("execute_command")
    return names


def validate_manifests(registered_names: set[str], settings: Settings) -> None:
    expected = active_names(settings)
    if registered_names != expected:
        raise RuntimeError(
            "manifest coverage mismatch: "
            f"missing={sorted(expected - registered_names)}, "
            f"orphaned={sorted(registered_names - expected)}"
        )
    for manifest in MANIFESTS.values():
        if manifest.timeout_ms <= 0:
            raise RuntimeError(f"invalid timeout for {manifest.name}")
        if manifest.retryable and not manifest.idempotent:
            raise RuntimeError(f"retryable capability lacks idempotency proof: {manifest.name}")
        if manifest.side_effects != "read" and manifest.retryable:
            raise RuntimeError(f"mutation must default to non-retryable: {manifest.name}")
        if manifest.requires_approval and manifest.side_effects == "read":
            raise RuntimeError(f"read capability unexpectedly requires approval: {manifest.name}")
