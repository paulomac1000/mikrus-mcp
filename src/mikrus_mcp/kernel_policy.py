"""Policy and retry mixin for the invocation kernel."""

from __future__ import annotations

import asyncio
import random
import weakref
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from mikrus_mcp.approvals import ApprovalRegistry
from mikrus_mcp.client import Client
from mikrus_mcp.config import Settings
from mikrus_mcp.errors import AppError, ErrorCode
from mikrus_mcp.manifests import CapabilityManifest
from mikrus_mcp.targets import TargetRegistry
from mikrus_mcp.validators import (
    ValidationError,
    validate_command,
    validate_container_name,
    validate_content_size,
    validate_domain,
    validate_hours_param,
    validate_lines_param,
    validate_path,
    validate_port,
    validate_process_target,
    validate_search_pattern,
    validate_service_action,
    validate_service_name,
)


if TYPE_CHECKING:
    from mikrus_mcp.kernel import CallerContext


class PolicyMixin:
    settings: Settings
    registry: TargetRegistry
    approvals: ApprovalRegistry
    _operation_locks: weakref.WeakValueDictionary[str, asyncio.Lock]
    _sleep: Callable[[float], Awaitable[None]]

    if TYPE_CHECKING:
        async def _execute(
            self,
            name: str,
            target: str,
            arguments: dict[str, Any],
            *,
            client: Client | None = None,
        ) -> Any: ...

    @staticmethod
    def _has_scope(scopes: frozenset[str], required: str) -> bool:
        if required in scopes:
            return True
        namespace = required.split(":", 1)[0]
        return f"{namespace}:*" in scopes

    def _authorize_selector(
        self,
        caller: CallerContext,
        manifest: CapabilityManifest,
        target: str,
    ) -> None:
        if not caller.principal:
            raise AppError(ErrorCode.AUTHENTICATION, "principal is not authenticated")
        missing = [
            scope
            for scope in manifest.required_scopes
            if not self._has_scope(caller.scopes, scope)
        ]
        if missing:
            raise AppError(
                ErrorCode.AUTHORIZATION,
                "principal lacks required capability scope",
            )
        if manifest.target_required and not (
            self._has_scope(caller.scopes, f"target:{target}")
        ):
            raise AppError(
                ErrorCode.AUTHORIZATION, "principal is not authorized for target"
            )

    @staticmethod
    def _resource(manifest: CapabilityManifest, arguments: dict[str, Any]) -> str:
        if manifest.resource_argument:
            value = arguments.get(manifest.resource_argument)
            return str(value) if value not in (None, "") else "<target>"
        return "<target>"

    def _validate_arguments(
        self, name: str, arguments: dict[str, Any], manifest: CapabilityManifest
    ) -> dict[str, Any]:
        if not isinstance(arguments, dict):
            raise ValidationError("arguments must be an object")
        normalized = dict(arguments)
        allowed: dict[str, set[str]] = {
            "describe_mikrus_capabilities": set(),
            "list_configured_servers": set(),
            "get_server_info": set(),
            "list_servers": set(),
            "get_server_stats": set(),
            "restart_server": set(),
            "get_logs": set(),
            "get_log_by_id": {"log_id"},
            "boost_server": set(),
            "get_db_info": set(),
            "get_ports": set(),
            "get_cloud": set(),
            "assign_domain": {"port", "domain"},
            "execute_command": {"cmd"},
            "read_file": {"path"},
            "write_file": {"path", "content"},
            "get_service_status": {"name"},
            "change_service_state": {"name", "action"},
            "analyze_disk": {"path"},
            "check_port": {"port"},
            "list_processes": set(),
            "terminate_process": {"target"},
            "update_system": set(),
            "list_directory": {"path"},
            "tail_file": {"path", "lines"},
            "search_in_files": {"path", "pattern"},
            "get_memory_info": set(),
            "get_network_info": set(),
            "get_process_tree": set(),
            "list_docker_containers": set(),
            "get_docker_logs": {"container", "lines"},
            "get_docker_stats": set(),
            "get_journal_logs": {"unit", "lines"},
            "find_system_errors": {"hours"},
            "search_journal_logs": {"term", "lines"},
        }
        expected = allowed.get(name)
        if expected is None:
            raise ValidationError(f"unknown capability: {name}")
        permitted = expected | ({"server"} if manifest.target_required else set())
        unknown = set(normalized) - permitted
        if unknown:
            raise ValidationError(f"unexpected arguments: {', '.join(sorted(unknown))}")
        if manifest.target_required:
            selector = normalized.get("server")
            if selector is not None and (not isinstance(selector, str) or not selector):
                raise ValidationError("server must be a non-empty target name")

        def required_text(field: str, *, maximum: int = 1_000) -> str:
            value = normalized.get(field)
            if not isinstance(value, str) or not value or len(value) > maximum:
                raise ValidationError(
                    f"{field} must be a non-empty string up to {maximum} characters"
                )
            return value

        match name:
            case "get_log_by_id":
                value = required_text("log_id", maximum=128)
                if not all(
                    character.isalnum() or character in "_-" for character in value
                ):
                    raise ValidationError("Invalid log ID")
            case "assign_domain":
                normalized["port"] = str(validate_port(normalized.get("port")))
                normalized["domain"] = validate_domain(
                    required_text("domain", maximum=253)
                )
            case "execute_command":
                normalized["cmd"] = validate_command(
                    required_text("cmd", maximum=4_096)
                )
            case "read_file" | "list_directory" | "analyze_disk":
                normalized["path"] = validate_path(required_text("path"))
            case "write_file":
                normalized["path"] = validate_path(
                    required_text("path"), for_write=True
                )
                content = normalized.get("content")
                validate_content_size(content)
            case "get_service_status":
                normalized["name"] = validate_service_name(
                    required_text("name", maximum=255)
                )
            case "change_service_state":
                normalized["name"] = validate_service_name(
                    required_text("name", maximum=255)
                )
                action = validate_service_action(required_text("action", maximum=32))
                if action in {"status", "is-active", "is-enabled"}:
                    raise ValidationError(
                        "read-only service actions use get_service_status"
                    )
                normalized["action"] = action
            case "check_port":
                normalized["port"] = str(validate_port(normalized.get("port")))
            case "terminate_process":
                normalized["target"] = validate_process_target(
                    required_text("target", maximum=128)
                )
            case "tail_file":
                normalized["path"] = validate_path(required_text("path"))
                normalized["lines"] = validate_lines_param(normalized.get("lines", 50))
            case "search_in_files":
                normalized["path"] = validate_path(required_text("path"))
                normalized["pattern"] = validate_search_pattern(
                    required_text("pattern")
                )
            case "get_docker_logs":
                normalized["container"] = validate_container_name(
                    required_text("container", maximum=128)
                )
                normalized["lines"] = validate_lines_param(normalized.get("lines", 50))
            case "get_journal_logs":
                normalized["unit"] = validate_service_name(
                    required_text("unit", maximum=255)
                )
                normalized["lines"] = validate_lines_param(normalized.get("lines", 50))
            case "find_system_errors":
                normalized["hours"] = validate_hours_param(normalized.get("hours", 1))
            case "search_journal_logs":
                normalized["term"] = validate_search_pattern(required_text("term"))
                normalized["lines"] = validate_lines_param(normalized.get("lines", 50))
        return normalized

    def _authorize_mutation(
        self,
        manifest: CapabilityManifest,
    ) -> None:
        if manifest.side_effects == "read":
            return
        if not self.settings.write_enabled:
            raise AppError(
                ErrorCode.AUTHORIZATION,
                "write operations are disabled by operator policy",
            )
        if manifest.command_profile and not self.settings.command_execution_enabled:
            raise AppError(
                ErrorCode.AUTHORIZATION, "command execution profile is disabled"
            )

    def _approval_available(
        self,
        caller: CallerContext,
        manifest: CapabilityManifest,
        target: str,
        arguments: dict[str, Any],
    ) -> None:
        if not manifest.requires_approval:
            return
        resource = self._resource(manifest, arguments)
        if not self.approvals.has_matching(
            manifest.name, caller.principal, target, resource
        ):
            raise AppError(
                ErrorCode.AUTHORIZATION,
                "a valid one-time server-side approval record is required",
            )

    def _consume_approval(
        self,
        caller: CallerContext,
        manifest: CapabilityManifest,
        target: str,
        arguments: dict[str, Any],
    ) -> None:
        if not manifest.requires_approval:
            return
        resource = self._resource(manifest, arguments)
        if not self.approvals.consume_matching(
            manifest.name, caller.principal, target, resource
        ):
            raise AppError(
                ErrorCode.AUTHORIZATION,
                "the server-side approval expired or was consumed before execution",
            )

    def _lock_key(
        self,
        manifest: CapabilityManifest,
        target: str,
        arguments: dict[str, Any],
    ) -> str | None:
        match manifest.concurrency_scope:
            case "none":
                if not manifest.concurrent_safe:
                    raise RuntimeError(
                        "manifest "
                        f"{manifest.name} declares unsafe concurrency with no scope"
                    )
                return None
            case "target":
                return f"target:{target}"
            case "target-capability":
                return f"target:{target}:capability:{manifest.name}"
            case "target-resource":
                resource = self._resource(manifest, arguments)
                return f"target:{target}:capability:{manifest.name}:resource:{resource}"
            case _:
                raise RuntimeError(
                    f"unsupported concurrency scope for {manifest.name}: "
                    f"{manifest.concurrency_scope}"
                )

    def _lock_for(
        self, manifest: CapabilityManifest, target: str, arguments: dict[str, Any]
    ) -> asyncio.Lock | None:
        key = self._lock_key(manifest, target, arguments)
        if key is None:
            return None
        lock = self._operation_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._operation_locks[key] = lock
        return lock

    @staticmethod
    def _retry_condition(error: AppError) -> str | None:
        return {
            ErrorCode.RATE_LIMITED: "rate-limit",
            ErrorCode.UPSTREAM: "transient-upstream",
            ErrorCode.TIMEOUT: "timeout",
        }.get(error.code)

    async def _execute_with_policy_retry(
        self,
        manifest: CapabilityManifest,
        name: str,
        target: str,
        arguments: dict[str, Any],
        *,
        client: Client | None = None,
    ) -> Any:
        maximum_attempts = 3 if manifest.retry_conditions else 1
        for attempt in range(maximum_attempts):
            try:
                return await self._execute(name, target, arguments, client=client)
            except AppError as exc:
                condition = self._retry_condition(exc)
                allowed = (
                    manifest.idempotent
                    and manifest.retryable
                    and condition in manifest.retry_conditions
                )
                if not allowed or attempt + 1 >= maximum_attempts:
                    if allowed and not exc.retryable:
                        raise AppError(
                            exc.code,
                            exc.message,
                            retryable=True,
                            retry_after_seconds=exc.retry_after_seconds,
                        ) from exc
                    raise
                base_delay = (
                    exc.retry_after_seconds
                    if exc.retry_after_seconds is not None
                    else min(4.0, float(2**attempt))
                )
                await self._sleep(min(60.0, base_delay + random.uniform(0.0, 0.25)))
        raise AssertionError("policy retry loop exhausted")
