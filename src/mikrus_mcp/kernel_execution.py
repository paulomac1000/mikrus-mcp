"""Backend execution and failure-result mixin for the invocation kernel."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, TypedDict

from mikrus_mcp import __version__
from mikrus_mcp.client import Client
from mikrus_mcp.config import Settings
from mikrus_mcp.cron_profiles import (
    CronProfileRecord,
    CronProfileRegistry,
    generate_cron_line,
    marker_count,
    marker_line,
    profile_state,
    remove_from_text,
    scan_installed,
    upsert_in_text,
    validate_installed_text,
)
from mikrus_mcp.docker_ops import (
    PlanRecord,
    PlanRecordStore,
    canonical_json_bytes,
    desired_from_compose,
    encode_receipt,
    live_state,
    plan_output,
    project_inspect,
    ps_labels,
    receipt_digest,
    receipt_payload,
    semantic_diff,
    states_equal,
)
from mikrus_mcp.errors import AppError, ErrorCode
from mikrus_mcp.jobs import ProgramJobRegistry
from mikrus_mcp.provenance import ProvenanceSnapshot
from mikrus_mcp.remote_jobs import DurableRemoteJobRegistry, request_digest
from mikrus_mcp.sanitizer import sanitize_data
from mikrus_mcp.targets import TargetRegistry

if TYPE_CHECKING:
    from mikrus_mcp.kernel import CallerContext


class _ErrorProvenance(TypedDict):
    capability: str | None
    capability_version: str | None
    target: str | None
    target_identity: str | None
    backend: str | None


class ExecutionMixin:
    settings: Settings
    registry: TargetRegistry
    program_jobs: ProgramJobRegistry
    remote_jobs: DurableRemoteJobRegistry | None
    cron_profiles: CronProfileRegistry | None
    docker_plans: PlanRecordStore | None
    _provenance: ProvenanceSnapshot

    if TYPE_CHECKING:

        def catalog(self, *, active_only: bool = False) -> list[dict[str, object]]: ...

    @staticmethod
    def _error_provenance(
        manifest: Any,
        target: str,
        target_identity: str | None,
        target_config: Any,
    ) -> _ErrorProvenance:
        """Expose only provenance that is safe at the reached authorization phase."""
        configured = target_config is not None
        return {
            "capability": manifest.name if manifest is not None else None,
            "capability_version": manifest.version if manifest is not None else None,
            "target": target if configured else None,
            "target_identity": target_identity,
            "backend": target_config.type if configured else None,
        }

    async def _docker_resolve_target(
        self,
        client: Client,
        *,
        service: str,
        project: str | None,
    ) -> tuple[str, list[str], dict[str, Any]]:
        """Resolve the live compose project, config files, and primary container."""
        filtered = await client.docker_ps_filter(service=service, project=project)
        containers = filtered.get("containers") or []
        if not containers:
            raise AppError(
                ErrorCode.NOT_FOUND,
                "no running compose container matches the service (NOT_FOUND)",
            )
        projects = {ps_labels(item).get("com.docker.compose.project", "") for item in containers}
        if project is None and len(projects) > 1:
            raise AppError(
                ErrorCode.CONFLICT,
                "the service exists in multiple compose projects; pass compose_project "
                "(AMBIGUOUS_SERVICE)",
            )
        live_project = next(iter(sorted(projects)))
        primary = sorted(containers, key=lambda item: str(item.get("ID") or item.get("Id") or ""))[
            0
        ]
        primary_id = str(primary.get("ID") or primary.get("Id") or "")
        inspect_result = await client.docker_inspect([primary_id])
        inspected = inspect_result.get("containers") or []
        if not inspected:
            raise AppError(
                ErrorCode.NOT_FOUND,
                "the compose container could not be inspected (NOT_FOUND)",
            )
        config_files_label = ps_labels(primary).get("com.docker.compose.project.config_files", "")
        files = [item for item in config_files_label.split(",") if item]
        return live_project, files, inspected[0]

    @staticmethod
    def _docker_check_binding(
        *,
        live_project: str,
        live_files: list[str],
        project: str | None,
        files: list[str] | None,
    ) -> None:
        if project is not None and project != live_project:
            raise AppError(
                ErrorCode.CONFLICT,
                "the explicit compose project does not match the live container label "
                "(COMPOSE_PROJECT_MISMATCH)",
            )
        if files is not None and sorted(files) != sorted(live_files):
            raise AppError(
                ErrorCode.CONFLICT,
                "the live config_files label differs from the supplied compose_files "
                "(DECLARED_RUNTIME_DRIFT)",
            )

    async def _docker_compose_desired(
        self,
        client: Client,
        *,
        service: str,
        project: str,
        files: list[str],
        desired_image: str | None,
    ) -> tuple[dict[str, Any], str, str, list[str]]:
        """Resolve compose-desired state plus the image reference and content digest."""
        config_result = await client.docker_compose_config(project=project, files=files)
        config = config_result.get("config")
        if not isinstance(config, dict):
            raise AppError(
                ErrorCode.UPSTREAM,
                "compose config returned no service mapping (COMPOSE_CONFIG_FAILED)",
            )
        try:
            desired = desired_from_compose(config, service)
        except KeyError:
            raise AppError(
                ErrorCode.NOT_FOUND,
                "the service is absent from the compose configuration (NOT_FOUND)",
            ) from None
        image_ref = desired_image or desired["image_ref"]
        if not image_ref:
            raise AppError(
                ErrorCode.VALIDATION,
                "the compose service has no image reference; supply desired_image "
                "(UNSUPPORTED_CONFIGURATION)",
            )
        image_result = await client.docker_image_inspect(image_ref)
        image_payload = image_result.get("image") or {}
        image_digest = str(image_payload.get("Id") or "")
        desired = {**desired, "image_id": image_digest}
        return desired, str(image_ref), image_digest, files

    async def _docker_load_plan_record(self, arguments: dict[str, Any]) -> tuple[str, PlanRecord]:
        if self.docker_plans is None:
            raise AppError(ErrorCode.UNAVAILABLE, "the docker plan store is not configured")
        record_digest = receipt_digest(str(arguments["plan_receipt"]))
        record = self.docker_plans.get(record_digest)
        if record is None:
            raise AppError(
                ErrorCode.CONFLICT,
                "the plan record is missing or expired; re-plan required (PLAN_STALE)",
            )
        service = str(arguments["service"])
        if record.service != service:
            raise AppError(
                ErrorCode.VALIDATION,
                "the plan receipt belongs to a different service (VALIDATION_FAILED)",
            )
        return service, record

    async def _docker_service_wait_branch(
        self,
        client: Client,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        service = str(arguments["service"])
        readiness = str(arguments.get("readiness", "running"))
        timeout_seconds = float(arguments.get("timeout_seconds", 10))
        project: str | None = None
        files: list[str] | None = None
        if arguments.get("plan_receipt") is not None:
            service, record = await self._docker_load_plan_record(arguments)
            project = record.project
            files = record.compose_files
        live_project, live_files, inspected = await self._docker_resolve_target(
            client, service=service, project=project
        )
        self._docker_check_binding(
            live_project=live_project,
            live_files=live_files,
            project=project,
            files=files,
        )
        wait = await client.docker_service_wait(
            container_id=str(inspected.get("Id") or ""),
            readiness=readiness,
            timeout_seconds=timeout_seconds,
        )
        return {
            "status": "READY",
            "service": service,
            "project": live_project,
            "readiness": readiness,
            "state": str(wait.get("state") or ""),
            "health": wait.get("health"),
        }

    async def _docker_plan(
        self,
        client: Client,
        *,
        service: str,
        project: str | None,
        files: list[str] | None,
        desired_image: str | None,
        allow_runtime_drift: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
        """Shared plan computation: returns (output, desired, live, receipt payload)."""
        live_project, live_files, inspected = await self._docker_resolve_target(
            client, service=service, project=project
        )
        self._docker_check_binding(
            live_project=live_project,
            live_files=live_files,
            project=project,
            files=files,
        )
        desired, image_ref, image_digest, bound_files = await self._docker_compose_desired(
            client,
            service=service,
            project=live_project,
            files=live_files,
            desired_image=desired_image,
        )
        payload = receipt_payload(
            service=service,
            project=live_project,
            compose_files=bound_files,
            desired_image_explicit=desired_image is not None,
            desired=desired,
            image_digest=image_digest,
        )
        receipt = encode_receipt(payload)
        live = live_state(inspected)
        differences = semantic_diff(live, desired, project=live_project)
        output = plan_output(
            receipt=receipt,
            service=service,
            project=live_project,
            compose_files=bound_files,
            desired=desired,
            image_digest=image_digest,
            differences=differences,
            allow_runtime_drift=allow_runtime_drift,
        )
        return output, desired, live, payload

    async def _execute(
        self,
        name: str,
        target: str,
        arguments: dict[str, Any],
        *,
        client: Client | None = None,
        caller: CallerContext | None = None,
    ) -> Any:
        if name == "describe_mikrus_capabilities":
            return {
                "schema_version": __version__,
                "server_version": __version__,
                "supported_transports": ["stdio", "streamable-http"],
                "supported": self.catalog(active_only=False),
                "active": self.catalog(active_only=True),
                "provenance": self._provenance.as_dict(),
            }
        if name == "list_configured_servers":
            return self.registry.status(self.settings.default_target)

        if caller is None:
            raise AppError(
                ErrorCode.INTERNAL,
                "caller context is required for capability execution",
            )

        if name == "get_program_status":
            return await self.program_jobs.status(
                job_id=str(arguments["job_id"]), principal=caller.principal
            )
        if name == "get_program_result":
            return await self.program_jobs.result(
                job_id=str(arguments["job_id"]), principal=caller.principal
            )
        if name == "cancel_program":
            return await self.program_jobs.cancel(
                job_id=str(arguments["job_id"]), principal=caller.principal
            )

        if name == "remote_job_start":
            if self.remote_jobs is None:
                raise AppError(ErrorCode.UNAVAILABLE, "durable remote jobs are not configured")
            now = datetime.now(UTC).isoformat()
            digest = request_digest(
                {key: value for key, value in arguments.items() if key != "server"}
            )
            record, reused = self.remote_jobs.create_or_reuse(
                principal=caller.principal,
                server_id=target,
                target_identity=client.stable_identity if client is not None else "",
                idempotency_key=str(arguments["idempotency_key"]),
                request_digest_value=digest,
                now=now,
            )
            if not reused:
                if client is None:
                    client = await self.registry.get(target)
                try:
                    await client.remote_job_start(
                        job_id=record.job_id,
                        request_digest=digest,
                        executable=str(arguments["executable"]),
                        argv=list(arguments.get("argv", [])),
                        cwd=arguments.get("cwd"),
                        stdin=arguments.get("stdin"),
                    )
                except AppError as exc:
                    if exc.code == ErrorCode.AMBIGUOUS:
                        try:
                            remote = await client.remote_job_status(job_id=record.job_id)
                        except AppError:
                            self.remote_jobs.mark_lost(
                                job_id=record.job_id, principal=caller.principal, now=now
                            )
                            raise AppError(
                                exc.code,
                                "the remote launch outcome could not be reconciled; "
                                "reconcile target state before retry (AMBIGUOUS_OUTCOME)",
                            ) from exc
                        remote_state = remote.get("state")
                        if remote_state in {
                            "queued",
                            "running",
                            "succeeded",
                            "failed",
                            "cancelled",
                            "lost",
                            "expired",
                        }:
                            self.remote_jobs.reconcile_observed_state(
                                principal=caller.principal,
                                server_id=target,
                                job_id=record.job_id,
                                observed_state=remote_state,
                                now=datetime.now(UTC).isoformat(),
                            )
                        return {
                            **remote,
                            "reused": True,
                            "reconciled_after_ambiguity": True,
                        }
                    self.remote_jobs.mark_lost(
                        job_id=record.job_id, principal=caller.principal, now=now
                    )
                    raise
                except Exception:
                    self.remote_jobs.mark_lost(
                        job_id=record.job_id, principal=caller.principal, now=now
                    )
                    raise
            return {**record.as_dict(), "reused": reused}

        if name in {
            "remote_job_status",
            "remote_job_wait",
            "remote_job_result",
            "remote_job_output",
            "remote_job_cancel",
        }:
            if self.remote_jobs is None or client is None:
                raise AppError(ErrorCode.UNAVAILABLE, "durable remote jobs are not configured")
            job_id = str(arguments["job_id"])
            if name == "remote_job_status":
                remote = await client.remote_job_status(job_id=job_id)
            elif name == "remote_job_wait":
                remote = await client.remote_job_wait(
                    job_id=job_id, timeout_seconds=float(arguments.get("timeout_seconds", 30))
                )
            elif name == "remote_job_result":
                remote = await client.remote_job_result(job_id=job_id)
            elif name == "remote_job_output":
                remote = await client.remote_job_output(
                    job_id=job_id,
                    stream=str(arguments["stream"]),
                    offset=int(arguments.get("offset", 0)),
                    max_bytes=int(arguments.get("max_bytes", 65_536)),
                )
            else:
                remote = await client.remote_job_cancel(
                    job_id=job_id, reason=str(arguments.get("reason", "operator request"))
                )
            state = remote.get("state")
            if state in {"running", "succeeded", "failed", "cancelled", "lost", "expired"}:
                self.remote_jobs.reconcile_observed_state(
                    principal=caller.principal,
                    server_id=target,
                    job_id=job_id,
                    observed_state=state,
                    now=datetime.now(UTC).isoformat(),
                )
            return remote

        if name == "file_patch_atomic":
            if client is None:
                client = await self.registry.get(target)
            return await client.file_patch_atomic(
                path=str(arguments["path"]),
                expected_digest=str(arguments["expected_digest"]),
                content_b64=str(arguments["content_b64"]),
            )

        if name == "cron_list":
            if self.cron_profiles is None:
                raise AppError(ErrorCode.UNAVAILABLE, "cron profiles are not configured")
            if client is None:
                client = await self.registry.get(target)
            installed = await client.cron_read()
            text = validate_installed_text(str(installed.get("text", "")))
            observed = scan_installed(text)
            profiles = self.cron_profiles.store.find_for(
                principal=caller.principal, server_id=target
            )
            items: list[dict[str, Any]] = []
            for profile in profiles:
                generated = generate_cron_line(
                    schedule=profile.schedule,
                    executable=profile.executable,
                    argv=profile.argv,
                    environment=profile.environment,
                )
                marker_digests = observed.get(profile.profile_id, [])
                items.append(
                    {
                        "profile_id": profile.profile_id,
                        "state": profile_state(
                            observed,
                            profile_id=profile.profile_id,
                            generated_line=generated,
                            digest=profile.desired_digest,
                        ),
                        "desired_digest": profile.desired_digest,
                        "observed_digest": marker_digests[0] if marker_digests else None,
                        "schedule": dict(profile.schedule),
                    }
                )
            return {
                "profiles": items,
                "count": len(items),
                "installed_hash": str(installed.get("hash", "")),
                "installed_size": int(installed.get("size", 0)),
            }

        if name == "cron_upsert":
            if self.cron_profiles is None:
                raise AppError(ErrorCode.UNAVAILABLE, "cron profiles are not configured")
            if client is None:
                client = await self.registry.get(target)
            now = datetime.now(UTC).isoformat()
            profile = CronProfileRecord(
                profile_id=str(arguments["profile_id"]),
                principal=caller.principal,
                server_id=target,
                target_identity=client.stable_identity,
                schedule=dict(arguments["schedule"]),
                executable=str(arguments["executable"]),
                argv=list(arguments.get("argv", [])),
                environment=dict(arguments.get("environment", {})),
                created_at=now,
                updated_at=now,
            )
            generated = generate_cron_line(
                schedule=profile.schedule,
                executable=profile.executable,
                argv=profile.argv,
                environment=profile.environment,
            )
            profile.with_projection(generated)
            installed = await client.cron_read()
            text = validate_installed_text(str(installed.get("text", "")))
            observed = scan_installed(text)
            if marker_count(observed, profile.profile_id) > 1:
                raise AppError(
                    ErrorCode.CONFLICT,
                    "installed crontab contains duplicate markers (DUPLICATE_MARKER)",
                )
            new_text = upsert_in_text(
                text,
                profile_id=profile.profile_id,
                generated_line=generated,
                digest=profile.desired_digest,
            )
            await client.cron_install(
                expected_hash=str(installed.get("hash", "")), new_text=new_text
            )
            self.cron_profiles.store.upsert(profile)
            return {
                "profile_id": profile.profile_id,
                "state": "IN_SYNC",
                "desired_digest": profile.desired_digest,
                "marker": marker_line(profile.profile_id, profile.desired_digest),
            }

        if name == "cron_remove":
            if self.cron_profiles is None:
                raise AppError(ErrorCode.UNAVAILABLE, "cron profiles are not configured")
            if client is None:
                client = await self.registry.get(target)
            profile_id = str(arguments["profile_id"])
            self.cron_profiles.store.get(
                profile_id=profile_id, principal=caller.principal, server_id=target
            )
            installed = await client.cron_read()
            text = validate_installed_text(str(installed.get("text", "")))
            observed = scan_installed(text)
            if marker_count(observed, profile_id) > 1:
                raise AppError(
                    ErrorCode.CONFLICT,
                    "installed crontab contains duplicate markers (DUPLICATE_MARKER)",
                )
            if marker_count(observed, profile_id) == 0:
                raise AppError(
                    ErrorCode.NOT_FOUND,
                    "cron profile marker is absent from the installed crontab (PROFILE_NOT_FOUND)",
                )
            new_text = remove_from_text(text, profile_id=profile_id)
            await client.cron_install(
                expected_hash=str(installed.get("hash", "")), new_text=new_text
            )
            self.cron_profiles.store.delete(
                profile_id=profile_id, principal=caller.principal, server_id=target
            )
            return {"profile_id": profile_id, "removed": True}

        if name == "docker_runtime_snapshot":
            if client is None:
                client = await self.registry.get(target)
            service = arguments.get("service")
            container = arguments.get("container")
            if container is not None:
                inspect_result = await client.docker_inspect([str(container)])
                inspected = inspect_result.get("containers") or []
                if not inspected:
                    raise AppError(
                        ErrorCode.NOT_FOUND,
                        "docker container not found (NOT_FOUND)",
                    )
                return {"containers": [project_inspect(inspected[0])]}
            if not isinstance(service, str):
                raise AppError(ErrorCode.VALIDATION, "service selector is required")
            filtered = await client.docker_ps_filter(service=service)
            matches = filtered.get("containers") or []
            if not matches:
                raise AppError(
                    ErrorCode.NOT_FOUND,
                    "no compose container matches the service (NOT_FOUND)",
                )
            projects = {ps_labels(item).get("com.docker.compose.project", "") for item in matches}
            if len(projects) > 1:
                raise AppError(
                    ErrorCode.CONFLICT,
                    "the service exists in multiple compose projects; inspect by container "
                    "or pass a project (AMBIGUOUS_SERVICE)",
                )
            identifiers = [
                str(item.get("ID") or item.get("Id") or "")
                for item in sorted(
                    matches, key=lambda entry: str(entry.get("ID") or entry.get("Id") or "")
                )
            ][:8]
            inspect_result = await client.docker_inspect(identifiers)
            inspected = inspect_result.get("containers") or []
            return {"containers": [project_inspect(entry) for entry in inspected]}

        if name == "docker_recreate_plan":
            if client is None:
                client = await self.registry.get(target)
            if self.docker_plans is None:
                raise AppError(ErrorCode.UNAVAILABLE, "the docker plan store is not configured")
            allow_runtime_drift = bool(arguments.get("allow_runtime_drift", False))
            output, _, _, payload = await self._docker_plan(
                client,
                service=str(arguments["service"]),
                project=arguments.get("compose_project"),
                files=arguments.get("compose_files"),
                desired_image=arguments.get("desired_image"),
                allow_runtime_drift=allow_runtime_drift,
            )
            self.docker_plans.save(
                receipt_digest=receipt_digest(str(output["plan_receipt"])),
                service=str(arguments["service"]),
                project=str(output["project"]),
                compose_files=list(output["compose_files"]),
                desired_image=arguments.get("desired_image"),
                desired_image_explicit=arguments.get("desired_image") is not None,
                allow_runtime_drift=allow_runtime_drift,
                has_runtime_drift=bool(output["has_runtime_only_drift"]),
                payload=payload,
            )
            return output

        if name == "docker_recreate_apply":
            if client is None:
                client = await self.registry.get(target)
            service, plan_record = await self._docker_load_plan_record(arguments)
            output, desired, live, fresh_payload = await self._docker_plan(
                client,
                service=service,
                project=plan_record.project,
                files=plan_record.compose_files,
                desired_image=plan_record.desired_image,
                allow_runtime_drift=plan_record.allow_runtime_drift,
            )
            if plan_record.has_runtime_drift and not plan_record.allow_runtime_drift:
                raise AppError(
                    ErrorCode.RECREATE_CONFIG_DRIFT,
                    "the live state carries runtime-only drift that the plan did not "
                    "explicitly accept; re-plan with allow_runtime_drift=true",
                )
            fresh = canonical_json_bytes(fresh_payload)
            stored = canonical_json_bytes(record_payload := plan_record.payload)
            if fresh != stored:
                if fresh_payload["desired"] != record_payload["desired"]:
                    raise AppError(
                        ErrorCode.CONFLICT,
                        "the compose-desired state changed since planning (PLAN_STALE)",
                    )
                if plan_record.desired_image_explicit:
                    raise AppError(
                        ErrorCode.CONFLICT,
                        "the pinned image digest changed since planning (PLAN_STALE)",
                    )
                raise AppError(
                    ErrorCode.CONFLICT,
                    "the image tag no longer resolves to the planned digest; "
                    "re-plan required (IMAGE_DRIFT)",
                )
            if states_equal(live, desired, project=str(output["project"])):
                return {
                    "status": "ALREADY_APPLIED",
                    "plan_receipt": output["plan_receipt"],
                    "service": service,
                    "project": output["project"],
                    "post_state": None,
                    "post_verified": True,
                    "post_wait": None,
                }
            await client.docker_compose_up(
                project=str(output["project"]),
                files=list(output["compose_files"]),
                service=service,
            )
            post_state: dict[str, Any] | None
            post_wait: dict[str, Any] | None = None
            try:
                post_project, post_files, post_inspected = await self._docker_resolve_target(
                    client, service=service, project=str(output["project"])
                )
                post_state = project_inspect(post_inspected)
            except AppError as verify_error:
                raise AppError(
                    verify_error.code,
                    "the recreate executed but post-apply verification failed; "
                    "applied=true; reconcile target state before retry "
                    f"({verify_error.code.value})",
                ) from verify_error
            recreated_config = post_inspected.get("Config") or {}
            readiness = arguments.get("readiness") or (
                "healthy" if recreated_config.get("Healthcheck") else "running"
            )
            timeout_seconds = float(arguments.get("timeout_seconds", 15))
            try:
                waited = await client.docker_service_wait(
                    container_id=str(post_inspected.get("Id") or ""),
                    readiness=str(readiness),
                    timeout_seconds=timeout_seconds,
                )
                post_wait = {
                    "status": "READY",
                    "readiness": str(readiness),
                    "state": str(waited.get("state") or ""),
                    "health": waited.get("health"),
                }
            except AppError as wait_error:
                raise AppError(
                    wait_error.code,
                    f"the recreate executed but the readiness wait failed; "
                    f"applied=true; reconcile target state before retry "
                    f"({wait_error.code.value})",
                ) from wait_error
            return {
                "status": "APPLIED",
                "plan_receipt": output["plan_receipt"],
                "service": service,
                "project": output["project"],
                "post_state": post_state,
                "post_verified": True,
                "post_wait": post_wait,
            }

        if name == "service_wait":
            if client is None:
                client = await self.registry.get(target)
            return await self._docker_service_wait_branch(client, arguments)

        if client is None:
            client = await self.registry.get(target)

        args = {key: value for key, value in arguments.items() if key != "server"}
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
                return await client.get_journal_logs(str(args["unit"]), int(args.get("lines", 50)))
            case "find_system_errors":
                return await client.find_system_errors(int(args.get("hours", 1)))
            case "search_journal_logs":
                return await client.search_journal_logs(
                    str(args["term"]), int(args.get("lines", 50))
                )
            case "execute_program":
                return await client.execute_program(
                    str(args["executable"]),
                    list(args.get("argv", [])),
                    args.get("cwd"),
                    args.get("stdin"),
                )
            case "start_program":
                return await self.program_jobs.submit(
                    principal=caller.principal,
                    target=target,
                    target_identity=client.stable_identity,
                    client=client,
                    executable=str(args["executable"]),
                    argv=list(args.get("argv", [])),
                    cwd=args.get("cwd"),
                    stdin=args.get("stdin"),
                )
            case _:
                raise AppError(ErrorCode.NOT_FOUND, f"unknown capability: {name}")

    def _failure(
        self,
        code: ErrorCode,
        message: str,
        request_id: str,
        started: float,
        *,
        retryable: bool = False,
        retry_after_seconds: float | None = None,
        capability: str | None = None,
        capability_version: str | None = None,
        target: str | None = None,
        target_identity: str | None = None,
        backend: str | None = None,
    ) -> dict[str, Any]:
        error: dict[str, Any] = {
            "code": code.value,
            "message": str(sanitize_data(message)),
            "retryable": retryable,
        }
        if retry_after_seconds is not None:
            error["retry_after_seconds"] = retry_after_seconds
        meta: dict[str, Any] = {
            "request_id": request_id,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "provenance": self._provenance.as_dict(),
        }
        provenance = {
            "capability": capability,
            "capability_version": capability_version,
            "source": "mikrus-mcp" if capability else None,
            "artifact": f"mikrus-mcp=={__version__}" if capability else None,
            "target": target,
            "target_identity": target_identity,
            "backend": backend,
        }
        meta.update({key: value for key, value in provenance.items() if value is not None})
        return {
            "success": False,
            "error": error,
            "_meta": meta,
        }
