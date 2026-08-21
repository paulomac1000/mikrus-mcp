"""Backend execution and failure-result mixin for the invocation kernel."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, TypedDict

from mikrus_mcp import __version__
from mikrus_mcp.client import Client
from mikrus_mcp.config import Settings
from mikrus_mcp.errors import AppError, ErrorCode
from mikrus_mcp.sanitizer import sanitize_data
from mikrus_mcp.targets import TargetRegistry


class _ErrorProvenance(TypedDict):
    capability: str | None
    capability_version: str | None
    target: str | None
    target_identity: str | None
    backend: str | None


class ExecutionMixin:
    settings: Settings
    registry: TargetRegistry

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

    async def _execute(
        self,
        name: str,
        target: str,
        arguments: dict[str, Any],
        *,
        client: Client | None = None,
    ) -> Any:
        if name == "describe_mikrus_capabilities":
            return {
                "schema_version": __version__,
                "server_version": __version__,
                "supported_transports": ["stdio", "streamable-http"],
                "supported": self.catalog(active_only=False),
                "active": self.catalog(active_only=True),
            }
        if name == "list_configured_servers":
            return self.registry.status(self.settings.default_target)

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
