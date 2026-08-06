"""One invocation kernel for policy, target binding, execution, and telemetry."""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

from mikrus_mcp.approvals import ApprovalRegistry
from mikrus_mcp.errors import AppError, ErrorCode
from mikrus_mcp.manifests import MANIFESTS, CapabilityManifest, active_names
from mikrus_mcp.sanitizer import sanitize_data
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

logger = logging.getLogger(__name__)

_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "mikrus_mcp_request_id", default=None
)


@dataclass(frozen=True, slots=True)
class CallerContext:
    principal: str
    scopes: frozenset[str]
    approval_token: str | None = None


class InvocationKernel:
    """Enforce the same policy for every MCP and test invocation."""

    _MIKRUS_ONLY = frozenset(
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

    def __init__(
        self,
        settings: Settings,
        registry: TargetRegistry | None = None,
        approvals: ApprovalRegistry | None = None,
    ) -> None:
        self.settings = settings.validate()
        self.registry = registry or TargetRegistry(dict(settings.targets))
        self.approvals = approvals or ApprovalRegistry.from_file(settings.approval_file)
        self._operation_locks: dict[str, asyncio.Lock] = {}

    @property
    def active_names(self) -> set[str]:
        return active_names(self.settings)

    def catalog(self, *, active_only: bool = False) -> list[dict[str, object]]:
        names = self.active_names if active_only else set(MANIFESTS)
        result = []
        for name in sorted(names):
            value = MANIFESTS[name].as_dict()
            value["active"] = name in self.active_names
            if name == "execute_command" and name not in self.active_names:
                value["inactive_reason"] = "command execution profile is disabled"
            result.append(value)
        return result

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
            raise AppError(ErrorCode.AUTHORIZATION, "principal lacks required capability scope")
        if manifest.target_required and not (
            self._has_scope(caller.scopes, f"target:{target}")
        ):
            raise AppError(ErrorCode.AUTHORIZATION, "principal is not authorized for target")

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
                if not all(character.isalnum() or character in "_-" for character in value):
                    raise ValidationError("Invalid log ID")
            case "assign_domain":
                normalized["port"] = str(validate_port(normalized.get("port")))
                normalized["domain"] = validate_domain(required_text("domain", maximum=253))
            case "execute_command":
                normalized["cmd"] = validate_command(required_text("cmd", maximum=4_096))
            case "read_file" | "list_directory" | "analyze_disk":
                normalized["path"] = validate_path(required_text("path"))
            case "write_file":
                normalized["path"] = validate_path(required_text("path"), for_write=True)
                content = normalized.get("content")
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
                normalized["port"] = str(validate_port(normalized.get("port")))
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
        return normalized

    def _authorize_mutation(
        self,
        caller: CallerContext,
        manifest: CapabilityManifest,
        target: str,
        arguments: dict[str, Any],
    ) -> None:
        if manifest.side_effects == "read":
            return
        if not self.settings.write_enabled:
            raise AppError(
                ErrorCode.AUTHORIZATION,
                "write operations are disabled by operator policy",
            )
        if manifest.command_profile and not self.settings.command_execution_enabled:
            raise AppError(ErrorCode.AUTHORIZATION, "command execution profile is disabled")
        resource = self._resource(manifest, arguments)
        if manifest.requires_approval and not self.approvals.consume(
            caller.approval_token, manifest.name, caller.principal, target, resource
        ):
            raise AppError(
                ErrorCode.AUTHORIZATION,
                "a valid one-time server-side approval record is required",
            )

    def _lock_for(
        self, manifest: CapabilityManifest, target: str, arguments: dict[str, Any]
    ) -> asyncio.Lock | None:
        if manifest.concurrent_safe:
            return None
        key = f"{target}:{manifest.name}:{self._resource(manifest, arguments)}"
        return self._operation_locks.setdefault(key, asyncio.Lock())

    async def invoke(
        self,
        name: str,
        arguments: dict[str, Any],
        caller: CallerContext,
    ) -> dict[str, Any]:
        request_id = uuid.uuid4().hex
        token = _request_id.set(request_id)
        started = time.monotonic()
        target = self.settings.default_target
        try:
            manifest = MANIFESTS.get(name)
            if manifest is None or name not in self.active_names:
                raise AppError(ErrorCode.NOT_FOUND, f"unknown or inactive capability: {name}")
            normalized = self._validate_arguments(name, arguments, manifest)
            target = str(normalized.get("server") or self.settings.default_target)
            if manifest.target_required:
                self.registry.config(target)
            self._authorize_selector(caller, manifest, target)
            self._authorize_mutation(caller, manifest, target, normalized)

            lock = self._lock_for(manifest, target, normalized)
            timeout_seconds = min(
                manifest.timeout_ms, self.settings.default_deadline_ms
            ) / 1000
            async with asyncio.timeout(timeout_seconds):
                if lock is None:
                    data = await self._execute(name, target, normalized)
                else:
                    async with lock:
                        data = await self._execute(name, target, normalized)
            sanitized = sanitize_data(data)
            encoded = json.dumps(sanitized, ensure_ascii=False, default=str).encode("utf-8")
            if len(encoded) > self.settings.max_result_bytes:
                raise AppError(ErrorCode.UPSTREAM, "result exceeds configured size limit")
            return {
                "success": True,
                "data": sanitized,
                "_meta": {
                    "request_id": request_id,
                    "target": target if manifest.target_required else None,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                },
            }
        except ValidationError as exc:
            return self._failure(ErrorCode.VALIDATION, str(exc), request_id, started)
        except AppError as exc:
            return self._failure(
                exc.code,
                exc.message,
                request_id,
                started,
                retryable=exc.retryable,
                retry_after_seconds=exc.retry_after_seconds,
            )
        except TimeoutError:
            return self._failure(
                ErrorCode.TIMEOUT,
                "operation deadline exceeded",
                request_id,
                started,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Invocation failed with an internal error")
            return self._failure(
                ErrorCode.INTERNAL,
                "internal operation failure",
                request_id,
                started,
            )
        finally:
            _request_id.reset(token)

    async def _execute(self, name: str, target: str, arguments: dict[str, Any]) -> Any:
        if name == "describe_mikrus_capabilities":
            return {
                "schema_version": "2.0.0",
                "server_version": "2.0.0",
                "supported_transports": ["stdio", "streamable-http"],
                "supported": self.catalog(active_only=False),
                "active": self.catalog(active_only=True),
            }
        if name == "list_configured_servers":
            return self.registry.status(self.settings.default_target)

        client = await self.registry.get(target)
        if name in self._MIKRUS_ONLY and self.registry.config(target).type != "mikrus":
            raise AppError(ErrorCode.VALIDATION, f"target '{target}' is not a mikr.us target")

        args = {
            key: value
            for key, value in arguments.items()
            if key not in {"server", "approval_token"}
        }
        match name:
            case "get_server_info":
                return await client.get_server_info()
            case "list_servers":
                return await client.list_servers()
            case "get_server_stats":
                return await client.get_server_stats()
            case "restart_server":
                return await client.restart_server()
            case "get_logs":
                return await client.get_logs()
            case "get_log_by_id":
                return await client.get_log_by_id(str(args["log_id"]))
            case "boost_server":
                return await client.boost_server()
            case "get_db_info":
                return await client.get_db_info()
            case "get_ports":
                return await client.get_ports()
            case "get_cloud":
                return await client.get_cloud()
            case "assign_domain":
                return await client.assign_domain(str(args["port"]), str(args["domain"]))
            case "execute_command":
                return await client.execute_command(str(args["cmd"]))
            case "read_file":
                return await client.read_file(str(args["path"]))
            case "write_file":
                return await client.write_file(str(args["path"]), str(args["content"]))
            case "get_service_status":
                return await client.get_service_status(str(args["name"]))
            case "change_service_state":
                return await client.change_service_state(str(args["name"]), str(args["action"]))
            case "analyze_disk":
                return await client.analyze_disk(str(args.get("path", "/")))
            case "check_port":
                return await client.check_port(str(args["port"]))
            case "list_processes":
                return await client.list_processes()
            case "terminate_process":
                return await client.terminate_process(str(args["target"]))
            case "update_system":
                return await client.update_system()
            case "list_directory":
                return await client.list_directory(str(args["path"]))
            case "tail_file":
                return await client.tail_file(str(args["path"]), int(args.get("lines", 50)))
            case "search_in_files":
                return await client.search_in_files(str(args["path"]), str(args["pattern"]))
            case "get_memory_info":
                return await client.get_memory_info()
            case "get_network_info":
                return await client.get_network_info()
            case "get_process_tree":
                return await client.get_process_tree()
            case "list_docker_containers":
                return await client.list_docker_containers()
            case "get_docker_logs":
                return await client.get_docker_logs(
                    str(args["container"]), int(args.get("lines", 50))
                )
            case "get_docker_stats":
                return await client.get_docker_stats()
            case "get_journal_logs":
                return await client.get_journal_logs(
                    str(args["unit"]), int(args.get("lines", 50))
                )
            case "find_system_errors":
                return await client.find_system_errors(int(args.get("hours", 1)))
            case "search_journal_logs":
                return await client.search_journal_logs(
                    str(args["term"]), int(args.get("lines", 50))
                )
            case _:
                raise AppError(ErrorCode.NOT_FOUND, f"unknown capability: {name}")

    @staticmethod
    def _failure(
        code: ErrorCode,
        message: str,
        request_id: str,
        started: float,
        *,
        retryable: bool = False,
        retry_after_seconds: float | None = None,
    ) -> dict[str, Any]:
        error: dict[str, Any] = {
            "code": code.value,
            "message": str(sanitize_data(message)),
            "retryable": retryable,
        }
        if retry_after_seconds is not None:
            error["retry_after_seconds"] = retry_after_seconds
        return {
            "success": False,
            "error": error,
            "_meta": {
                "request_id": request_id,
                "duration_ms": int((time.monotonic() - started) * 1000),
            },
        }

    async def close(self) -> None:
        await self.registry.close()
