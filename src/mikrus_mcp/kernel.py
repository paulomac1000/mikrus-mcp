"""One invocation kernel for policy, target binding, execution, and telemetry."""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import time
import uuid
import weakref
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from mikrus_mcp.approvals import ApprovalRegistry, normalized_arguments_digest
from mikrus_mcp.client import Client
from mikrus_mcp.config import Settings
from mikrus_mcp.errors import AppError, ErrorCode
from mikrus_mcp.kernel_execution import ExecutionMixin
from mikrus_mcp.kernel_policy import PolicyMixin
from mikrus_mcp.manifests import MANIFESTS, CapabilityManifest, active_names, inactive_reason
from mikrus_mcp.sanitizer import sanitize_data
from mikrus_mcp.targets import TargetRegistry
from mikrus_mcp.validators import ValidationError

logger = logging.getLogger(__name__)
_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "mikrus_mcp_request_id", default=None
)


@dataclass(frozen=True, slots=True)
class CallerContext:
    principal: str
    scopes: frozenset[str]


class InvocationKernel(PolicyMixin, ExecutionMixin):
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
        self._operation_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = (
            weakref.WeakValueDictionary()
        )
        self._sleep: Callable[[float], Awaitable[None]] = asyncio.sleep

    @property
    def active_names(self) -> set[str]:
        return active_names(self.settings)

    def catalog(self, *, active_only: bool = False) -> list[dict[str, object]]:
        names = self.active_names if active_only else set(MANIFESTS)
        result: list[dict[str, object]] = []
        for name in sorted(names):
            reason = inactive_reason(name, self.settings)
            result.append(
                MANIFESTS[name].as_dict(
                    active_state="active" if reason is None else "inactive",
                    inactive_reason=reason,
                )
            )
        return result

    def health(self) -> dict[str, object]:
        dependency_health = self.registry.status(self.settings.default_target)
        targets = dependency_health.get("targets", [])
        default_status = next(
            (
                item.get("status")
                for item in targets
                if isinstance(item, dict) and item.get("name") == self.settings.default_target
            ),
            "unavailable",
        )
        degraded = [
            {"capability": name, "reason": reason}
            for name in sorted(MANIFESTS)
            if (reason := inactive_reason(name, self.settings)) is not None
        ]
        return {
            "startup_complete": True,
            "live": True,
            "ready": bool(self.active_names) and default_status != "unavailable",
            "dependency_health": dependency_health,
            "capability_degradation": degraded,
            "shutdown_owned": True,
        }

    async def invoke(
        self,
        name: str,
        arguments: dict[str, Any],
        caller: CallerContext,
        *,
        deadline_ms: int | None = None,
    ) -> dict[str, Any]:
        request_id = uuid.uuid4().hex
        token = _request_id.set(request_id)
        started = time.monotonic()
        target = self.settings.default_target
        target_identity = "<none>"
        mutation_execution_started = False
        try:
            manifest = MANIFESTS.get(name)
            if manifest is None or name not in self.active_names:
                raise AppError(ErrorCode.NOT_FOUND, f"unknown or inactive capability: {name}")
            normalized = self._validate_arguments(name, arguments, manifest)
            target = str(normalized.get("server") or self.settings.default_target)
            target_config = None
            if manifest.target_required:
                target_config = self.registry.config(target)
                target_identity = target_config.stable_identity
                if name in self._MIKRUS_ONLY and target_config.type != "mikrus":
                    raise AppError(
                        ErrorCode.VALIDATION,
                        f"target '{target}' is not a mikr.us target",
                    )
            self._authorize_selector(caller, manifest, target)
            self._authorize_mutation(manifest)
            arguments_digest = normalized_arguments_digest(normalized)
            resource = self._resource(manifest, normalized)
            prepared_client: Client | None = None
            if manifest.target_required and manifest.requires_approval:
                prepared_client = await self.registry.get(target)
                target_identity = prepared_client.stable_identity
            if manifest.requires_approval and not self.approvals.has_matching(
                manifest.name,
                caller.principal,
                target_identity,
                resource,
                arguments_digest,
            ):
                raise AppError(
                    ErrorCode.AUTHORIZATION,
                    "a valid one-time server-side approval record is required",
                )

            lock = self._lock_for(manifest, target, normalized)
            requested_deadline = (
                self.settings.default_deadline_ms if deadline_ms is None else deadline_ms
            )
            if not 100 <= requested_deadline <= self.settings.server_max_deadline_ms:
                raise AppError(ErrorCode.VALIDATION, "request deadline is outside server policy")
            timeout_seconds = min(
                manifest.timeout_ms, requested_deadline, self.settings.server_max_deadline_ms
            ) / 1000

            async def execute_once_locked() -> Any:
                nonlocal mutation_execution_started
                if manifest.requires_approval and not self.approvals.consume_matching(
                    manifest.name,
                    caller.principal,
                    target_identity,
                    resource,
                    arguments_digest,
                ):
                    raise AppError(
                        ErrorCode.AUTHORIZATION,
                        "the server-side approval expired or was consumed before execution",
                    )
                if manifest.side_effects != "read":
                    mutation_execution_started = True
                return await self._execute_with_policy_retry(
                    manifest,
                    name,
                    target,
                    normalized,
                    client=prepared_client,
                )

            async with asyncio.timeout(timeout_seconds):
                if lock is None:
                    data = await execute_once_locked()
                else:
                    async with lock:
                        data = await execute_once_locked()
            if manifest.target_required:
                resolved_identity = self.registry.resolved_identity(target)
                if resolved_identity is not None:
                    target_identity = resolved_identity
            sanitized = sanitize_data(data)
            result: dict[str, Any] = {
                "success": True,
                "data": sanitized,
                "_meta": {
                    "request_id": request_id,
                    "capability": manifest.name,
                    "capability_version": manifest.version,
                    "source": "mikrus-mcp",
                    "artifact": "mikrus-mcp==2.0.0",
                    "target": target if manifest.target_required else None,
                    "target_identity": target_identity if manifest.target_required else None,
                    "backend": target_config.type if target_config is not None else None,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                },
            }
            encoded = json.dumps(result, ensure_ascii=False, default=str).encode("utf-8")
            response_limit = min(self.settings.max_result_bytes, manifest.max_response_bytes)
            if len(encoded) > response_limit:
                raise AppError(ErrorCode.UPSTREAM, "result exceeds configured size limit")
            return result
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
            if mutation_execution_started:
                return self._failure(
                    ErrorCode.AMBIGUOUS,
                    "mutation outcome is unknown after the operation deadline expired; "
                    "reconcile target state before retry",
                    request_id,
                    started,
                )
            return self._failure(
                ErrorCode.TIMEOUT, "operation deadline exceeded", request_id, started
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Invocation failed with an internal error")
            return self._failure(
                ErrorCode.INTERNAL, "internal operation failure", request_id, started
            )
        finally:
            _request_id.reset(token)

    async def close(self) -> None:
        await self.registry.close()
