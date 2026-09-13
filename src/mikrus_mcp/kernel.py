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
from datetime import datetime, timezone
from typing import Any

from mikrus_mcp import __version__
from mikrus_mcp.approvals import ApprovalRegistry, normalized_arguments_digest
from mikrus_mcp.client import Client
from mikrus_mcp.config import Settings, TargetConfig
from mikrus_mcp.cron_profiles import CronProfileRegistry, CronProfileStore
from mikrus_mcp.docker_ops import PlanRecordStore
from mikrus_mcp.errors import AppError, ErrorCode
from mikrus_mcp.jobs import ProgramJobRegistry
from mikrus_mcp.kernel_execution import ExecutionMixin
from mikrus_mcp.kernel_policy import PolicyMixin
from mikrus_mcp.manifests import MANIFESTS, CapabilityManifest, active_names, inactive_reason
from mikrus_mcp.provenance import capture_runtime_provenance
from mikrus_mcp.remote_jobs import DurableRemoteJobRegistry, RemoteJobStore
from mikrus_mcp.sanitizer import sanitize_data
from mikrus_mcp.targets import TargetRegistry
from mikrus_mcp.validators import ValidationError

logger = logging.getLogger(__name__)
_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "mikrus_mcp_request_id", default=None
)
# The longest mutation adapter timeout is 65 seconds. Do not consume a one-time
# approval or enter a side-effecting adapter when less budget remains: otherwise
# the outer kernel timeout could preempt phase-aware pre/post-dispatch classification.
_MUTATION_CLASSIFICATION_BUDGET_MS = 65_000


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
    _SSH_ONLY = frozenset(
        {
            "execute_program",
            "start_program",
            "cancel_program",
            "remote_job_start",
            "file_patch_atomic",
            "cron_list",
            "cron_upsert",
            "cron_remove",
            "docker_runtime_snapshot",
            "docker_recreate_plan",
            "docker_recreate_apply",
            "service_wait",
        }
    )
    _REMOTE_JOB_LOOKUP = frozenset(
        {
            "remote_job_status",
            "remote_job_wait",
            "remote_job_result",
            "remote_job_output",
            "remote_job_cancel",
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
        self.program_jobs = ProgramJobRegistry()
        self.remote_jobs = (
            DurableRemoteJobRegistry(RemoteJobStore(self.settings.remote_job_store_file))
            if self.settings.remote_job_store_file is not None
            else None
        )
        self.cron_profiles = (
            CronProfileRegistry(CronProfileStore(self.settings.cron_profile_store_file))
            if self.settings.cron_profile_store_file is not None
            else None
        )
        self.docker_plans = (
            PlanRecordStore(self.settings.docker_plan_store_file)
            if self.settings.docker_plan_store_file is not None
            else None
        )
        self._provenance = capture_runtime_provenance()

    @property
    def active_names(self) -> set[str]:
        return active_names(self.settings)

    def catalog(self, *, active_only: bool = False) -> list[dict[str, object]]:
        names = self.active_names if active_only else set(MANIFESTS)
        config_generation = self._provenance.config_revision or self._provenance.instance_generation
        result: list[dict[str, object]] = []
        for name in sorted(names):
            reason = inactive_reason(name, self.settings)
            entry = MANIFESTS[name].as_dict(
                active_state="active" if reason is None else "inactive",
                inactive_reason=reason,
            )
            entry["config_generation"] = config_generation
            result.append(entry)
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
        ready = bool(self.active_names) and default_status == "connected"
        return {
            "startup_complete": True,
            "live": True,
            "ready": ready,
            "readiness_reason": None if ready else f"default target is {default_status}",
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
        target_identity: str | None = None
        mutation_execution_started = False
        manifest: CapabilityManifest | None = None
        target_config: TargetConfig | None = None
        try:
            manifest = MANIFESTS.get(name)
            if manifest is None or name not in self.active_names:
                raise AppError(ErrorCode.NOT_FOUND, f"unknown or inactive capability: {name}")
            normalized = self._validate_arguments(name, arguments, manifest)
            target = str(normalized.get("server") or self.settings.default_target)
            if name in {"get_program_status", "get_program_result", "cancel_program"}:
                target, target_identity = await self.program_jobs.target_binding(
                    job_id=str(normalized["job_id"]), principal=caller.principal
                )
                target_config = self.registry.config(target)
            if name in self._REMOTE_JOB_LOOKUP:
                if self.remote_jobs is None:
                    raise AppError(ErrorCode.UNAVAILABLE, "durable remote jobs are not configured")
                record = self.remote_jobs.get(
                    job_id=str(normalized["job_id"]), principal=caller.principal
                )
                target, target_identity = record.server_id, record.target_identity
                target_config = self.registry.config(target)
                if target_config.type != "ssh":
                    raise AppError(
                        ErrorCode.UNAVAILABLE,
                        "durable remote jobs require an SSH target",
                    )
            self._authorize_selector(caller, manifest, target)
            self._authorize_data_classification(caller, manifest)
            self._authorize_mutation(manifest)
            arguments_digest = normalized_arguments_digest(normalized)
            resource = self._resource(manifest, normalized)
            prepared_client: Client | None = None
            if manifest.target_required:
                target_config = self.registry.config(target)
                if name in self._MIKRUS_ONLY and target_config.type != "mikrus":
                    raise AppError(
                        ErrorCode.VALIDATION,
                        f"target '{target}' is not a mikr.us target",
                    )
                if name in self._SSH_ONLY and target_config.type != "ssh":
                    raise AppError(
                        ErrorCode.UNAVAILABLE,
                        f"capability '{name}' is unavailable for mikr.us targets",
                    )
                prepared_client = await self.registry.get(target)
                target_identity = prepared_client.stable_identity
                self._authorize_resolved_target(
                    caller,
                    manifest,
                    target_config,
                    target_identity,
                    resource,
                )
            elif target_identity is not None:
                self._authorize_resolved_target(
                    caller,
                    manifest,
                    target_config,
                    target_identity,
                    resource,
                )
                if name in self._REMOTE_JOB_LOOKUP:
                    prepared_client = await self.registry.get(target)
            if manifest.requires_approval and not self.approvals.has_matching(
                manifest.name,
                caller.principal,
                target_identity or "<none>",
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
            timeout_seconds = (
                min(manifest.timeout_ms, requested_deadline, self.settings.server_max_deadline_ms)
                / 1000
            )
            loop = asyncio.get_running_loop()
            expires_at = loop.time() + timeout_seconds

            async def execute_once_locked() -> Any:
                nonlocal mutation_execution_started
                if manifest.target_required:
                    current_identity = self.registry.resolved_identity(target)
                    if current_identity is None or current_identity != target_identity:
                        raise AppError(
                            ErrorCode.AUTHORIZATION,
                            "resolved target identity changed before execution",
                        )
                if (
                    manifest.side_effects != "read"
                    and manifest.timeout_ms >= _MUTATION_CLASSIFICATION_BUDGET_MS
                ):
                    remaining_ms = max(0, int((expires_at - loop.time()) * 1000))
                    if remaining_ms < _MUTATION_CLASSIFICATION_BUDGET_MS:
                        raise AppError(
                            ErrorCode.TIMEOUT,
                            "insufficient operation deadline remains to start the mutation safely; "
                            "the approval was not consumed",
                        )
                if manifest.requires_approval and not self.approvals.consume_matching(
                    manifest.name,
                    caller.principal,
                    target_identity or "<none>",
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
                    caller=caller,
                    expires_at=expires_at,
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
                    "artifact": f"mikrus-mcp=={__version__}",
                    "target": target if manifest.target_required else None,
                    "target_identity": target_identity if manifest.target_required else None,
                    "backend": target_config.type if target_config is not None else None,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                    "provenance": self._provenance.as_dict(),
                },
            }
            encoded = json.dumps(result, ensure_ascii=False, default=str).encode("utf-8")
            response_limit = min(self.settings.max_result_bytes, manifest.max_response_bytes)
            if len(encoded) > response_limit:
                raise AppError(ErrorCode.UPSTREAM, "result exceeds configured size limit")
            return result
        except ValidationError as exc:
            return self._failure(
                ErrorCode.VALIDATION,
                str(exc),
                request_id,
                started,
                **self._error_provenance(manifest, target, target_identity, target_config),
            )
        except AppError as exc:
            return self._failure(
                exc.code,
                exc.message,
                request_id,
                started,
                retryable=exc.retryable,
                retry_after_seconds=exc.retry_after_seconds,
                **self._error_provenance(manifest, target, target_identity, target_config),
            )
        except TimeoutError:
            if mutation_execution_started:
                return self._failure(
                    ErrorCode.AMBIGUOUS,
                    "mutation outcome is unknown after the operation deadline expired; "
                    "reconcile target state before retry",
                    request_id,
                    started,
                    **self._error_provenance(manifest, target, target_identity, target_config),
                )
            return self._failure(
                ErrorCode.TIMEOUT,
                "operation deadline exceeded",
                request_id,
                started,
                **self._error_provenance(manifest, target, target_identity, target_config),
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
                **self._error_provenance(manifest, target, target_identity, target_config),
            )
        finally:
            _request_id.reset(token)

    async def close(self) -> None:
        await self.program_jobs.close()
        await self.registry.close()
