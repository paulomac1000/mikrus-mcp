"""Single Source of Truth for all configuration defaults.

Every module MUST import defaults from this file.
No other file MAY define its own defaults for these values.
"""

import os
from typing import Any, Final

# API configuration
MIKRUS_API_URL = os.getenv("MIKRUS_API_URL", "https://api.mikr.us")

# Timeouts (seconds)
DEFAULT_HTTP_TIMEOUT: Final = 10.0
# Standard exception (mcp-server-standards.md rule 2.4 — [L1+] SHOULD 5-10s):
# the mikr.us /exec endpoint enforces a hard ~60s server-side execution limit.
# A client timeout below 60s would abort valid long-running commands, so 65s
# (60s API limit + 5s network margin) is used deliberately for /exec calls only.
# All non-exec HTTP calls use DEFAULT_HTTP_TIMEOUT.
EXEC_HTTP_TIMEOUT: Final = 65.0
SSH_DEFAULT_TIMEOUT: Final = 30

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Validation limits
MAX_TAIL_LINES: Final = 500
MAX_JOURNAL_LINES: Final = 500
MAX_SEARCH_RESULTS: Final = 100
MAX_GREP_HOURS: Final = 24
MAX_WRITE_SIZE: Final = 100_000

# Service actions
SERVICE_ACTIONS: Final = frozenset(
    {
        "status",
        "start",
        "stop",
        "restart",
        "enable",
        "disable",
        "is-active",
        "is-enabled",
    }
)

# Service actions that only read state — they do NOT require the write guard.
READ_ONLY_SERVICE_ACTIONS: Final = frozenset({"status", "is-active", "is-enabled"})

# Process actions
PROCESS_ACTIONS: Final = frozenset({"list", "kill"})

# Tool version — injected into every response _meta envelope
TOOLS_VERSION: Final = "1.1.0"

# Capability metadata schema version (describe_mikrus_capabilities)
CAPABILITIES_SCHEMA_VERSION: Final = "1.0.0"


def write_operations_enabled() -> bool:
    """Return True when write/destructive/command tools are authorized.

    Server-level authorization gate (mcp-server-standards.md — Write Guard, L2+).
    Controlled by the ENABLE_WRITE_OPERATIONS environment variable; defaults to
    false. Evaluated dynamically so the gate reflects the current environment.
    """
    return os.getenv("ENABLE_WRITE_OPERATIONS", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


# Tool manifests — machine-readable capability metadata (L2+).
#
# Manifests are built exclusively through the factory functions below so that
# every entry satisfies the Risk Consistency Matrix from mcp-server-standards.md.
# Picking the factory IS the criticality decision — there is no ad-hoc path.


def _make_read_manifest(
    name: str,
    *,
    timeout_ms: int = 5000,
    latency: str = "moderate",
    cost: str = "cheap",
    determinism: str = "env-dependent",
    side_effects: str = "none",
    concurrent_safe: bool = True,
) -> dict[str, Any]:
    """Manifest for a read-only tool with no side effects."""
    return {
        "name": name,
        "version": TOOLS_VERSION,
        "risk": "READ",
        "side_effects": side_effects,
        "idempotent": True,
        "retryable": True,
        "concurrent_safe": concurrent_safe,
        "timeout_ms": timeout_ms,
        "requires_confirmation": False,
        "determinism": determinism,
        "latency": latency,
        "cost": cost,
        "impact": "none",
        "privacy": "none",
        "reversible": True,
    }


def _make_write_manifest(
    name: str,
    *,
    timeout_ms: int = 10000,
    latency: str = "moderate",
    cost: str = "moderate",
    determinism: str = "env-dependent",
    impact: str = "persistent",
) -> dict[str, Any]:
    """Manifest for a reversible, retry-safe write tool."""
    return {
        "name": name,
        "version": TOOLS_VERSION,
        "risk": "WRITE",
        "side_effects": "write",
        "idempotent": True,
        "retryable": True,
        "concurrent_safe": False,
        "timeout_ms": timeout_ms,
        "requires_confirmation": True,
        "determinism": determinism,
        "latency": latency,
        "cost": cost,
        "impact": impact,
        "privacy": "none",
        "reversible": True,
    }


def _make_destructive_manifest(
    name: str,
    *,
    timeout_ms: int = 30000,
    latency: str = "slow",
    cost: str = "expensive",
    determinism: str = "env-dependent",
    impact: str = "service_outage",
) -> dict[str, Any]:
    """Manifest for an irreversible operation: reboot, service restart, kill."""
    return {
        "name": name,
        "version": TOOLS_VERSION,
        "risk": "DESTRUCTIVE",
        "side_effects": "destructive",
        "idempotent": False,
        "retryable": False,
        "concurrent_safe": False,
        "timeout_ms": timeout_ms,
        "requires_confirmation": True,
        "determinism": determinism,
        "latency": latency,
        "cost": cost,
        "impact": impact,
        "privacy": "none",
        "reversible": False,
    }


def _make_dangerous_manifest(
    name: str,
    *,
    timeout_ms: int = 60000,
    latency: str = "slow",
    cost: str = "expensive",
    determinism: str = "env-dependent",
    side_effects: str = "write",
    impact: str = "service_outage",
) -> dict[str, Any]:
    """Manifest for an arbitrary, unbounded shell-execution tool."""
    return {
        "name": name,
        "version": TOOLS_VERSION,
        "risk": "DANGEROUS",
        "side_effects": side_effects,
        "idempotent": False,
        "retryable": False,
        "concurrent_safe": False,
        "timeout_ms": timeout_ms,
        "requires_confirmation": True,
        "determinism": determinism,
        "latency": latency,
        "cost": cost,
        "impact": impact,
        "privacy": "none",
        "reversible": False,
    }


def _make_sensitive_manifest(
    name: str,
    *,
    timeout_ms: int = 5000,
    latency: str = "moderate",
    cost: str = "cheap",
    determinism: str = "env-dependent",
    side_effects: str = "none",
    privacy: str = "personal",
) -> dict[str, Any]:
    """Manifest for a read-only tool that returns credentials or sensitive data."""
    return {
        "name": name,
        "version": TOOLS_VERSION,
        "risk": "SENSITIVE",
        "side_effects": side_effects,
        "idempotent": True,
        "retryable": True,
        "concurrent_safe": True,
        "timeout_ms": timeout_ms,
        "requires_confirmation": True,
        "determinism": determinism,
        "latency": latency,
        "cost": cost,
        "impact": "none",
        "privacy": privacy,
        "reversible": True,
    }


# Every registered tool MUST have a manifest entry.
TOOL_MANIFESTS: dict[str, dict[str, Any]] = {
    # --- mikr.us API tools ---
    "get_server_info": _make_read_manifest("get_server_info", determinism="eventually-consistent"),
    "list_servers": _make_read_manifest("list_servers", determinism="eventually-consistent"),
    "get_server_stats": _make_read_manifest(
        "get_server_stats", determinism="eventually-consistent"
    ),
    "restart_server": _make_destructive_manifest("restart_server", timeout_ms=120000),
    "get_logs": _make_read_manifest("get_logs", determinism="eventually-consistent"),
    "get_log_by_id": _make_read_manifest("get_log_by_id", determinism="eventually-consistent"),
    "boost_server": _make_write_manifest("boost_server", cost="cheap", impact="transient"),
    "get_db_info": _make_sensitive_manifest("get_db_info"),
    "get_ports": _make_read_manifest("get_ports", determinism="eventually-consistent"),
    "get_cloud": _make_read_manifest("get_cloud", determinism="eventually-consistent"),
    "assign_domain": _make_write_manifest("assign_domain", cost="cheap", impact="persistent"),
    # --- system tools ---
    "execute_command": _make_dangerous_manifest("execute_command"),
    "read_file": _make_read_manifest("read_file"),
    "write_file": _make_write_manifest("write_file"),
    "manage_service": _make_destructive_manifest(
        "manage_service", timeout_ms=10000, latency="fast", cost="cheap"
    ),
    "analyze_disk": _make_read_manifest("analyze_disk", timeout_ms=15000, cost="moderate"),
    "check_port": _make_read_manifest("check_port", latency="fast"),
    "manage_process": _make_destructive_manifest(
        "manage_process", timeout_ms=10000, latency="fast", cost="cheap"
    ),
    "update_system": _make_write_manifest(
        "update_system", timeout_ms=120000, latency="slow", cost="expensive"
    ),
    "list_directory": _make_read_manifest("list_directory", latency="fast"),
    "tail_file": _make_read_manifest("tail_file", latency="fast"),
    "search_in_files": _make_read_manifest(
        "search_in_files", timeout_ms=30000, latency="slow", cost="moderate"
    ),
    "get_memory_info": _make_read_manifest("get_memory_info", latency="fast"),
    "get_network_info": _make_read_manifest("get_network_info", latency="fast"),
    "get_process_tree": _make_read_manifest("get_process_tree", latency="fast"),
    # --- container and journal tools ---
    "list_docker_containers": _make_read_manifest("list_docker_containers", timeout_ms=10000),
    "get_docker_logs": _make_read_manifest("get_docker_logs", timeout_ms=10000),
    "get_docker_stats": _make_read_manifest("get_docker_stats", timeout_ms=10000),
    "get_journal_logs": _make_sensitive_manifest(
        "get_journal_logs", timeout_ms=10000, cost="moderate"
    ),
    "find_system_errors": _make_read_manifest(
        "find_system_errors", timeout_ms=15000, cost="moderate"
    ),
    "search_journal_logs": _make_read_manifest(
        "search_journal_logs", timeout_ms=15000, cost="moderate"
    ),
    # --- discovery and introspection tools ---
    "list_configured_servers": _make_read_manifest(
        "list_configured_servers", timeout_ms=1000, latency="instant", determinism="deterministic"
    ),
    "describe_mikrus_capabilities": _make_read_manifest(
        "describe_mikrus_capabilities",
        timeout_ms=1000,
        latency="instant",
        determinism="deterministic",
    ),
}
