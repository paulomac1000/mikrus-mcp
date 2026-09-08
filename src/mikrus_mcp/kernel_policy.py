"""Policy and retry mixin for the invocation kernel."""

from __future__ import annotations

import asyncio
import hashlib
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
    validate_container_name,
    validate_content_size,
    validate_domain,
    validate_hours_param,
    validate_lines_param,
    validate_path,
    validate_port,
    validate_process_target,
    validate_program_arguments,
    validate_program_executable,
    validate_program_job_id,
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
            caller: CallerContext | None = None,
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
            scope for scope in manifest.required_scopes if not self._has_scope(caller.scopes, scope)
        ]
        if missing:
            raise AppError(
                ErrorCode.AUTHORIZATION,
                "principal lacks required capability scope",
            )
        if manifest.target_required and not self._has_scope(caller.scopes, f"target:{target}"):
            raise AppError(ErrorCode.AUTHORIZATION, "principal is not authorized for target")

    def _authorize_data_classification(
        self,
        caller: CallerContext,
        manifest: CapabilityManifest,
    ) -> None:
        if manifest.confidentiality == "public":
            return
        if not self._has_scope(caller.scopes, f"data:{manifest.confidentiality}"):
            raise AppError(
                ErrorCode.AUTHORIZATION,
                "principal is not authorized for the capability data classification",
            )

    @staticmethod
    def _resource_scope(manifest: CapabilityManifest, resource: str) -> str | None:
        if manifest.resource_argument is None:
            return None
        digest = hashlib.sha256(resource.encode("utf-8")).hexdigest()
        return f"resource:{manifest.name}:sha256:{digest}"

    def _authorize_resolved_target(
        self,
        caller: CallerContext,
        manifest: CapabilityManifest,
        target_config: Any,
        resolved_identity: str,
        resource: str,
    ) -> None:
        """Authorize the exact resolved backend identity and resource after resolution."""
        expected_identity = target_config.stable_identity
        if target_config.type == "ssh":
            verified_prefix = expected_identity + "#host-key=SHA256:"
            unverified = expected_identity + "#host-key=UNVERIFIED"
            identity_valid = (
                resolved_identity.startswith(verified_prefix)
                if target_config.verify_host_key
                else resolved_identity == unverified
            )
        else:
            identity_valid = resolved_identity == expected_identity
        if not identity_valid:
            raise AppError(ErrorCode.AUTHORIZATION, "resolved target identity changed")

        if not self._has_scope(caller.scopes, f"target-id:{resolved_identity}"):
            raise AppError(
                ErrorCode.AUTHORIZATION,
                "principal is not authorized for the resolved target identity",
            )
        resource_scope = self._resource_scope(manifest, resource)
        if resource_scope is not None and not self._has_scope(caller.scopes, resource_scope):
            raise AppError(
                ErrorCode.AUTHORIZATION,
                "principal is not authorized for the resolved resource",
            )
        if (
            target_config.type == "ssh"
            and not target_config.verify_host_key
            and manifest.side_effects != "read"
        ):
            raise AppError(
                ErrorCode.AUTHORIZATION,
                "mutations over unverified SSH host keys are prohibited",
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
            "execute_program": {"executable", "argv", "cwd", "stdin"},
            "start_program": {"executable", "argv", "cwd", "stdin"},
            "get_program_status": {"job_id"},
            "get_program_result": {"job_id"},
            "cancel_program": {"job_id"},
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
                if not all(character.isalnum() or character in "_-" for character in value):
                    raise ValidationError("Invalid log ID")
            case "assign_domain":
                port = normalized.get("port")
                if not isinstance(port, str | int):
                    raise ValidationError("port must be a string or integer")
                normalized["port"] = str(validate_port(port))
                normalized["domain"] = validate_domain(required_text("domain", maximum=253))
            case "read_file" | "list_directory" | "analyze_disk":
                normalized["path"] = validate_path(required_text("path"))
            case "write_file":
                normalized["path"] = validate_path(required_text("path"), for_write=True)
                content = normalized.get("content")
                if not isinstance(content, str):
                    raise ValidationError("content must be a string")
                validate_content_size(content)
            case "get_service_status":
                normalized["name"] = validate_service_name(required_text("name", maximum=255))
            case "change_service_state":
                normalized["name"] = validate_service_name(required_text("name", maximum=255))
                action = validate_service_action(required_text("action", maximum=32))
                if action in {"status", "is-active", "is-enabled"}:
                    raise ValidationError("read-only service actions use get_service_status")
                normalized["action"] = action
            case "check_port":
                port = normalized.get("port")
                if not isinstance(port, str | int):
                    raise ValidationError("port must be a string or integer")
                normalized["port"] = str(validate_port(port))
            case "terminate_process":
                normalized["target"] = validate_process_target(required_text("target", maximum=128))
            case "tail_file":
                normalized["path"] = validate_path(required_text("path"))
                normalized["lines"] = validate_lines_param(normalized.get("lines", 50))
            case "search_in_files":
                normalized["path"] = validate_path(required_text("path"))
                normalized["pattern"] = validate_search_pattern(required_text("pattern"))
            case "get_docker_logs":
                normalized["container"] = validate_container_name(
                    required_text("container", maximum=128)
                )
                normalized["lines"] = validate_lines_param(normalized.get("lines", 50))
            case "get_journal_logs":
                normalized["unit"] = validate_service_name(required_text("unit", maximum=255))
                normalized["lines"] = validate_lines_param(normalized.get("lines", 50))
            case "find_system_errors":
                normalized["hours"] = validate_hours_param(normalized.get("hours", 1))
            case "search_journal_logs":
                normalized["term"] = validate_search_pattern(required_text("term"))
                normalized["lines"] = validate_lines_param(normalized.get("lines", 50))
            case "execute_program" | "start_program":
                normalized["executable"] = validate_program_executable(
                    required_text("executable", maximum=255)
                )
                normalized["argv"] = validate_program_arguments(normalized.get("argv", []))
                if "cwd" in normalized and normalized["cwd"] is not None:
                    normalized["cwd"] = validate_path(required_text("cwd"))
                if "stdin" in normalized and normalized["stdin"] is not None:
                    validate_content_size(normalized["stdin"])
            case "get_program_status" | "get_program_result" | "cancel_program":
                normalized["job_id"] = validate_program_job_id(required_text("job_id", maximum=64))
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
                        f"manifest {manifest.name} declares unsafe concurrency with no scope"
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
            ErrorCode.TRANSIENT_UPSTREAM: "transient-upstream",
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
        caller: CallerContext | None = None,
        expires_at: float | None = None,
    ) -> Any:
        maximum_attempts = 3 if manifest.retry_conditions else 1
        for attempt in range(maximum_attempts):
            try:
                return await self._execute(name, target, arguments, client=client, caller=caller)
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
                delay = min(60.0, base_delay + random.uniform(0.0, 0.25))
                if expires_at is not None:
                    remaining = expires_at - asyncio.get_running_loop().time()
                    if remaining <= delay:
                        raise AppError(
                            exc.code,
                            exc.message,
                            retryable=True,
                            retry_after_seconds=(
                                exc.retry_after_seconds
                                if exc.retry_after_seconds is not None
                                else delay
                            ),
                        ) from exc
                await self._sleep(delay)
        raise AssertionError("policy retry loop exhausted")
