"""Application-owned capability manifests and active-catalog rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from mikrus_mcp import __version__
from mikrus_mcp.config import Settings

SideEffects = Literal["read", "write", "destructive"]
Confidentiality = Literal["public", "internal", "personal", "sensitive", "credential"]
RetryCondition = Literal["rate-limit", "transient-upstream", "timeout"]
ConcurrencyScope = Literal["none", "target", "target-capability", "target-resource"]

PROTOCOL_REVISIONS = ("2026-07-28", "2025-11-25")
DEFAULT_CAPABILITY_RESPONSE_BYTES = 1_000_000
# Mutation adapters use bounded timeouts up to 65 seconds for phase-aware
# classification. Keep the default capability budget above that adapter bound so
# the outer kernel deadline cannot preempt the adapter before it can distinguish
# a pre-dispatch failure from an ambiguous post-dispatch outcome.
DEFAULT_MUTATION_TIMEOUT_MS = 70_000
MIKRUS_ONLY = frozenset(
    {
        "get_server_info",
        "list_servers",
        "get_server_stats",
        "restart_server",
        "get_logs",
        "get_log_by_id",
        "boost_server",
        "get_db_info",
        "get_ports",
        "get_cloud",
        "assign_domain",
    }
)


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
    retry_conditions: tuple[RetryCondition, ...]
    concurrent_safe: bool
    concurrency_scope: ConcurrencyScope
    timeout_ms: int
    requires_approval: bool
    required_scopes: tuple[str, ...]
    target_binding: str
    target_required: bool = True
    resource_argument: str | None = None
    max_response_bytes: int = DEFAULT_CAPABILITY_RESPONSE_BYTES

    @property
    def risk(self) -> str:
        if self.side_effects in {"write", "destructive"}:
            return "high"
        if self.confidentiality in {"sensitive", "credential"}:
            return "medium"
        return "low"

    def as_dict(
        self,
        *,
        active_state: Literal["active", "inactive", "deprecated"] = "active",
        inactive_reason: str | None = None,
    ) -> dict[str, object]:
        # Advertise exactly what the runtime enforces: concurrent-safe reads run
        # unlocked, everything else serializes on one lock per scope key. Scope
        # names are passed through verbatim so manifest and policy share vocabulary.
        concurrency: dict[str, object] = (
            {"scope": "none", "serialized": False}
            if self.concurrent_safe
            else {"scope": self.concurrency_scope, "serialized": True, "limit": 1}
        )
        extensions: dict[str, object] = {
            "application_version": self.version,
            "confidentiality": self.confidentiality,
            "cost": self.cost,
            "retry_conditions": list(self.retry_conditions),
            "target_binding": self.target_binding,
            "target_required": self.target_required,
            "timeout_ms": self.timeout_ms,
        }
        if inactive_reason is not None:
            extensions["inactive_reason"] = inactive_reason
        result: dict[str, object] = {
            "schema_version": 1,
            "id": self.name,
            "name": self.name.replace("_", " ").capitalize(),
            "description": f"Application-owned {self.name.replace('_', ' ')} capability.",
            "operation_kind": self.side_effects,
            "risk": self.risk,
            "determinism": "environment-dependent",
            "latency": "bounded-long" if self.timeout_ms > 10_000 else "interactive",
            "impact": "none" if self.side_effects == "read" else "external",
            "active_state": active_state,
            "retryable": self.retryable if active_state == "active" else False,
            "idempotent": self.idempotent,
            "reversible": self.reversible,
            "requires_confirmation": self.requires_approval,
            "idempotency_key_required": False,
            "authorization_scopes": list(self.required_scopes),
            "concurrency": concurrency,
            "max_response_bytes": self.max_response_bytes,
            "protocol_revisions": list(PROTOCOL_REVISIONS),
            "extensions": extensions,
        }
        if self.requires_approval:
            result["approval"] = {
                "enforcement": "server-side",
                "record_required": True,
                "record_ttl_seconds_default": 60,
                "record_ttl_seconds_max": 300,
                "binds": [
                    "principal",
                    "capability",
                    "target",
                    "resource",
                    "arguments-digest",
                    "expires-at",
                ],
            }
        return result


def _read(
    name: str,
    confidentiality: Confidentiality = "internal",
    *,
    timeout_ms: int = 30_000,
    target_required: bool = True,
    resource_argument: str | None = None,
) -> CapabilityManifest:
    return CapabilityManifest(
        name=name,
        version=__version__,
        side_effects="read",
        confidentiality=confidentiality,
        operational_impact="none",
        cost="cheap",
        reversible=False,
        idempotent=True,
        idempotency_mechanism="natural read",
        retryable=True,
        retry_conditions=("rate-limit", "transient-upstream"),
        concurrent_safe=True,
        concurrency_scope="none",
        timeout_ms=timeout_ms,
        requires_approval=False,
        required_scopes=(f"tool:{name}",),
        target_binding="configured target resolved to a verified backend identity",
        target_required=target_required,
        resource_argument=resource_argument,
    )


def _mutation(
    name: str,
    *,
    destructive: bool = False,
    impact: str = "persistent",
    timeout_ms: int = DEFAULT_MUTATION_TIMEOUT_MS,
    resource_argument: str | None = None,
) -> CapabilityManifest:
    return CapabilityManifest(
        name=name,
        version=__version__,
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
        target_binding="verified backend identity plus approval-bound resource",
        resource_argument=resource_argument,
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
    "read_file": _read("read_file", "sensitive", resource_argument="path"),
    "write_file": _mutation("write_file", resource_argument="path"),
    "get_service_status": _read("get_service_status", resource_argument="name"),
    "change_service_state": _mutation(
        "change_service_state",
        destructive=True,
        impact="outage",
        resource_argument="name",
    ),
    "analyze_disk": _read("analyze_disk", timeout_ms=30_000, resource_argument="path"),
    "check_port": _read("check_port", resource_argument="port"),
    "list_processes": _read("list_processes", "sensitive"),
    "terminate_process": _mutation(
        "terminate_process",
        destructive=True,
        impact="outage",
        resource_argument="target",
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
    "get_docker_logs": _read("get_docker_logs", "sensitive", resource_argument="container"),
    "get_docker_stats": _read("get_docker_stats"),
    "get_journal_logs": _read("get_journal_logs", "sensitive", resource_argument="unit"),
    "find_system_errors": _read("find_system_errors", "sensitive"),
    "search_journal_logs": _read("search_journal_logs", "sensitive"),
    "list_configured_servers": _read(
        "list_configured_servers", "sensitive", timeout_ms=1_000, target_required=False
    ),
    "describe_mikrus_capabilities": _read(
        "describe_mikrus_capabilities", "public", timeout_ms=1_000, target_required=False
    ),
}


def inactive_reason(name: str, settings: Settings) -> str | None:
    manifest = MANIFESTS[name]
    if name in MIKRUS_ONLY and not any(
        target.type == "mikrus" for target in settings.targets.values()
    ):
        return "requires at least one configured mikr.us target"
    if manifest.side_effects != "read" and not settings.write_enabled:
        return "write operations are disabled by process policy"
    return None


def active_names(settings: Settings) -> set[str]:
    return {name for name in MANIFESTS if inactive_reason(name, settings) is None}


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
        if manifest.retryable and not manifest.retry_conditions:
            raise RuntimeError(f"retryable capability lacks retry conditions: {manifest.name}")
        if manifest.retry_conditions and not manifest.retryable:
            raise RuntimeError(f"retry conditions require retryable=true: {manifest.name}")
        if manifest.concurrent_safe != (manifest.concurrency_scope == "none"):
            raise RuntimeError(f"concurrency declaration is inconsistent for {manifest.name}")
