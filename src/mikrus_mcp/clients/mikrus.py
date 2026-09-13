"""Single-attempt mikr.us HTTP adapter."""

from __future__ import annotations

import asyncio
import html
import json
import re
import shlex
import time
from typing import Any

import httpx

from mikrus_mcp.clients.common import (
    RateLimiter,
    _CACHEABLE_ENDPOINTS,
    _CACHE_TTL_SECONDS,
    _remote_atomic_write_command,
    _remote_read_prefix,
)
from mikrus_mcp.errors import AppError, ErrorCode
from mikrus_mcp.sanitizer import sanitize_text
from mikrus_mcp.tools.constants import (
    DEFAULT_HTTP_TIMEOUT,
    EXEC_HTTP_TIMEOUT,
    MAX_JOURNAL_LINES,
    MAX_RESPONSE_BYTES,
    MAX_SEARCH_RESULTS,
)
from mikrus_mcp.validators import (
    ValidationError,
    validate_container_name,
    validate_domain,
    validate_hours_param,
    validate_lines_param,
    validate_port,
    validate_process_target,
    validate_search_pattern,
    validate_service_action,
    validate_service_name,
)

PROCESS_STATS_LIMIT = 50
_SECRET_ARGUMENT = re.compile(
    r"^--?(?:token|password|passwd|pwd|secret|api[-_]?key|cookie|authorization)$",
    re.IGNORECASE,
)


def _redact_process_command(command: str) -> str:
    try:
        parts = shlex.split(command)
    except ValueError:
        return "<REDACTED>"
    redacted: list[str] = []
    redact_next = False
    for part in parts:
        if redact_next:
            redacted.append("<REDACTED>")
            redact_next = False
        else:
            option, separator, value = part.partition("=")
            if separator and _SECRET_ARGUMENT.fullmatch(option):
                redacted.append(f"{option}=<REDACTED>")
                continue
            if _SECRET_ARGUMENT.fullmatch(part):
                redacted.append(part)
                redact_next = True
                continue
            redacted.append(sanitize_text(part))
    return " ".join(redacted)


def _parse_process_snapshot(raw: str) -> dict[str, Any]:
    """Parse a bounded ``ps aux`` snapshot without exposing secret argv values."""
    lines = html.unescape(raw).splitlines()
    records: list[dict[str, Any]] = []
    for line in lines:
        fields = line.split(None, 10)
        if len(fields) < 11 or not fields[1].isdigit():
            continue
        try:
            cpu = float(fields[2])
            memory = float(fields[3])
            rss = int(fields[5]) * 1024
        except ValueError:
            continue
        records.append(
            {
                "pid": int(fields[1]),
                "ppid": None,
                "user": fields[0],
                "cpuPercent": cpu,
                "memoryPercent": memory,
                "rssBytes": rss,
                "state": fields[7],
                "executable": fields[10].split(None, 1)[0] if fields[10] else None,
                "command": _redact_process_command(fields[10]) if fields[10] else None,
            }
        )
    if not records:
        return {
            "state": "partial",
            "error": {"code": "PROCESS_SNAPSHOT_UNAVAILABLE"},
            "processes": [],
            "processesTruncated": False,
            "processLimit": PROCESS_STATS_LIMIT,
            "processSort": "memory",
        }
    records.sort(key=lambda item: float(item["memoryPercent"]), reverse=True)
    return {
        "state": "complete",
        "processes": records[:PROCESS_STATS_LIMIT],
        "processesTruncated": len(records) > PROCESS_STATS_LIMIT,
        "processLimit": PROCESS_STATS_LIMIT,
        "processSort": "memory",
    }


class MikrusClient:
    """Async HTTP adapter bound to one immutable mikr.us server identity."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        server_name: str,
        *,
        requests_per_minute: int = 5,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not base_url.startswith("https://"):
            raise ValueError("mikr.us API URL must use HTTPS")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.server_name = server_name
        self.stable_identity = f"mikrus:{server_name}"
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._rate_limiter = RateLimiter(requests_per_minute)
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_lock = asyncio.Lock()

    def __repr__(self) -> str:
        return f"MikrusClient(server={self.server_name!r}, url={self.base_url!r})"

    async def open(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                transport=self._transport,
                follow_redirects=False,
                timeout=httpx.Timeout(DEFAULT_HTTP_TIMEOUT),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> MikrusClient:
        await self.open()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    @staticmethod
    def _retry_after(response: httpx.Response) -> float | None:
        raw = response.headers.get("Retry-After")
        if raw is None:
            return None
        try:
            value = float(raw)
        except ValueError:
            return None
        return max(0.0, min(value, 60.0))

    async def _cached(self, endpoint: str) -> Any | None:
        if endpoint not in _CACHEABLE_ENDPOINTS:
            return None
        async with self._cache_lock:
            item = self._cache.get(endpoint)
            if item is None:
                return None
            created, value = item
            if time.monotonic() - created >= _CACHE_TTL_SECONDS:
                self._cache.pop(endpoint, None)
                return None
            return value

    async def _store_cache(self, endpoint: str, value: Any) -> None:
        if endpoint in _CACHEABLE_ENDPOINTS:
            async with self._cache_lock:
                self._cache[endpoint] = (time.monotonic(), value)

    async def _request(
        self,
        endpoint: str,
        extra_data: dict[str, str] | None = None,
        *,
        timeout: float = DEFAULT_HTTP_TIMEOUT,
        mutation: bool = False,
    ) -> Any:
        """Perform one upstream request with phase-aware failure classification."""
        if self._client is None:
            raise AppError(ErrorCode.UNAVAILABLE, "HTTP client is not open")
        cached = await self._cached(endpoint)
        if cached is not None:
            return cached

        url = f"{self.base_url}{endpoint}"
        payload = {"srv": self.server_name, "key": self.api_key, **(extra_data or {})}
        await self._rate_limiter.acquire()
        try:
            response = await self._client.post(
                url,
                data=payload,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=timeout,
            )
        except (httpx.ConnectTimeout, httpx.PoolTimeout, httpx.ConnectError) as exc:
            raise AppError(
                ErrorCode.TRANSIENT_UPSTREAM,
                "mikr.us API could not be reached before request completion",
            ) from exc
        except httpx.TimeoutException as exc:
            code = ErrorCode.AMBIGUOUS if mutation else ErrorCode.TIMEOUT
            message = (
                "mutation outcome is unknown after an upstream timeout; "
                "reconcile target state before retry"
                if mutation
                else f"mikr.us API request exceeded {timeout:g} seconds"
            )
            raise AppError(code, message) from exc
        except httpx.HTTPError as exc:
            code = ErrorCode.AMBIGUOUS if mutation else ErrorCode.TRANSIENT_UPSTREAM
            message = (
                "mutation outcome is unknown after the upstream connection failed; "
                "reconcile target state before retry"
                if mutation
                else "mikr.us API connection failed transiently"
            )
            raise AppError(code, message) from exc

        raw_length = response.headers.get("Content-Length")
        if raw_length:
            try:
                declared_length = int(raw_length)
            except ValueError as exc:
                raise AppError(
                    ErrorCode.UPSTREAM_PROTOCOL, "invalid upstream Content-Length"
                ) from exc
            if declared_length > MAX_RESPONSE_BYTES:
                raise AppError(ErrorCode.UPSTREAM_PROTOCOL, "upstream response exceeds size limit")
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise AppError(ErrorCode.UPSTREAM_PROTOCOL, "upstream response exceeds size limit")

        if response.status_code == 429:
            raise AppError(
                ErrorCode.RATE_LIMITED,
                "mikr.us API rate limit reached",
                retry_after_seconds=self._retry_after(response),
            )
        if response.status_code != 200:
            reason = response.reason_phrase or "upstream request failed"
            if 500 <= response.status_code <= 599:
                code = ErrorCode.AMBIGUOUS if mutation else ErrorCode.TRANSIENT_UPSTREAM
                detail = (
                    "mutation outcome is unknown after an upstream server failure; "
                    "reconcile target state before retry"
                    if mutation
                    else f"mikr.us API returned transient HTTP {response.status_code}: {reason}"
                )
                raise AppError(code, detail)
            raise AppError(
                ErrorCode.UPSTREAM_REJECTED,
                f"mikr.us API rejected the request with HTTP {response.status_code}: {reason}",
            )

        if "application/json" in response.headers.get("content-type", ""):
            try:
                value = response.json()
            except json.JSONDecodeError as exc:
                raise AppError(
                    ErrorCode.UPSTREAM_PROTOCOL, "mikr.us API returned invalid JSON"
                ) from exc
        else:
            value = {"raw": response.text}
        await self._store_cache(endpoint, value)
        return value

    async def get_server_info(self) -> Any:
        return await self._request("/info")

    async def list_servers(self) -> Any:
        return await self._request("/serwery")

    async def get_server_stats(self) -> Any:
        result = await self._request("/stats")
        if isinstance(result, dict):
            normalized = {
                k: (html.unescape(v) if isinstance(v, str) else v) for k, v in result.items()
            }
            raw_processes = normalized.pop("ps", None)
            if isinstance(raw_processes, str):
                normalized["processSnapshot"] = _parse_process_snapshot(raw_processes)
            elif raw_processes is not None:
                normalized["ps"] = raw_processes
            return normalized
        return result

    async def restart_server(self) -> Any:
        return await self._request("/restart", timeout=EXEC_HTTP_TIMEOUT, mutation=True)

    async def get_logs(self) -> Any:
        return await self._request("/logs")

    async def get_log_by_id(self, log_id: str) -> Any:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", log_id):
            raise ValidationError("Invalid log ID")
        return await self._request(f"/logs/{log_id}")

    async def boost_server(self) -> Any:
        return await self._request("/amfetamina", mutation=True)

    async def get_db_info(self) -> Any:
        return await self._request("/db")

    async def get_ports(self) -> Any:
        return await self._request("/porty")

    async def get_cloud(self) -> Any:
        return await self._request("/cloud")

    async def assign_domain(self, port: str, domain: str) -> Any:
        validated_port = validate_port(port)
        validated_domain = validate_domain(domain)
        return await self._request(
            "/domain",
            {"port": str(validated_port), "domain": validated_domain},
            mutation=True,
        )

    @staticmethod
    def _check_exec_failure(result: Any) -> None:
        if isinstance(result, dict):
            output = str(result.get("output", "")).strip()
            if output == "błąd wykonania polecenia" or output.startswith("ERROR: błąd wykonania"):
                raise AppError(
                    ErrorCode.UPSTREAM,
                    f"remote command execution failed on mikr.us: {output}",
                )

    async def _exec_read(self, command: str, *, timeout: float = EXEC_HTTP_TIMEOUT) -> Any:
        result = await self._request("/exec", {"cmd": command}, timeout=timeout)
        self._check_exec_failure(result)
        return result

    async def _exec_mutation(self, command: str, *, timeout: float = EXEC_HTTP_TIMEOUT) -> Any:
        result = await self._request("/exec", {"cmd": command}, timeout=timeout, mutation=True)
        self._check_exec_failure(result)
        return result

    async def read_file(self, path: str) -> Any:
        prefix = _remote_read_prefix(path)
        return await self._exec_read(
            prefix
            + 'file -b --mime-encoding "$resolved" | grep -q binary && '
            + "echo 'ERROR: binary file' || head -n 200 -- \"$resolved\""
        )

    async def write_file(self, path: str, content: str) -> Any:
        return await self._exec_mutation(_remote_atomic_write_command(path, content))

    async def get_service_status(self, name: str) -> Any:
        service = shlex.quote(validate_service_name(name))
        return await self._exec_read(f"systemctl status --no-pager -- {service}")

    async def change_service_state(self, name: str, action: str) -> Any:
        service = shlex.quote(validate_service_name(name))
        action = validate_service_action(action)
        if action in {"status", "is-active", "is-enabled"}:
            raise ValidationError("read-only service actions use get_service_status")
        return await self._exec_mutation(f"systemctl {action} -- {service}")

    async def analyze_disk(self, path: str = "/") -> Any:
        return await self._exec_read(
            _remote_read_prefix(path)
            + 'df -h -- "$resolved"; echo ---TOP20---; '
            + 'du -sh -- "$resolved"/* 2>/dev/null | sort -rh | head -n 20',
            timeout=30.0,
        )

    async def check_port(self, port: str) -> Any:
        value = validate_port(port)
        return await self._exec_read(
            f"ss -tlnp 2>/dev/null | grep -F ':{value} ' || echo PORT_NOT_LISTENING"
        )

    async def list_processes(self) -> Any:
        return await self._exec_read("ps aux --sort=-%mem | head -n 20")

    async def terminate_process(self, target: str) -> Any:
        value = shlex.quote(validate_process_target(target))
        if target.isdigit():
            return await self._exec_mutation(f"kill -TERM -- {value}")
        return await self._exec_mutation(f"pkill -TERM -x -- {value}")

    async def update_system(self) -> Any:
        return await self._exec_mutation(
            "export DEBIAN_FRONTEND=noninteractive; apt-get update; "
            "apt-get upgrade -y -o Dpkg::Options::=--force-confdef "
            "-o Dpkg::Options::=--force-confold",
            timeout=120.0,
        )

    async def list_directory(self, path: str) -> Any:
        return await self._exec_read(_remote_read_prefix(path) + 'ls -la -- "$resolved"')

    async def tail_file(self, path: str, lines: int = 50) -> Any:
        count = validate_lines_param(lines)
        return await self._exec_read(_remote_read_prefix(path) + f'tail -n {count} -- "$resolved"')

    async def search_in_files(self, path: str, pattern: str) -> Any:
        term = shlex.quote(validate_search_pattern(pattern))
        return await self._exec_read(
            _remote_read_prefix(path)
            + f'grep -r -F -n --max-count={MAX_SEARCH_RESULTS} -- {term} "$resolved" '
            + f"2>/dev/null | head -n {MAX_SEARCH_RESULTS}",
            timeout=30.0,
        )

    async def get_memory_info(self) -> Any:
        return await self._exec_read("free -h")

    async def get_network_info(self) -> Any:
        return await self._exec_read("ip addr; echo ---PORTS---; ss -tlnp")

    async def get_process_tree(self) -> Any:
        return await self._exec_read("ps auxf | head -n 100")

    async def list_docker_containers(self) -> Any:
        return self._parse_docker_jsonl(await self._exec_read("docker ps -a --format '{{json .}}'"))

    async def get_docker_logs(self, container: str, lines: int = 50) -> Any:
        name = shlex.quote(validate_container_name(container))
        count = validate_lines_param(lines)
        return await self._exec_read(f"docker logs --tail {count} -- {name}")

    async def get_docker_stats(self) -> Any:
        return self._parse_docker_jsonl(
            await self._exec_read("docker stats --no-stream --format '{{json .}}'")
        )

    async def get_journal_logs(self, unit: str, lines: int = 50) -> Any:
        name = shlex.quote(validate_service_name(unit))
        count = validate_lines_param(lines, MAX_JOURNAL_LINES)
        return await self._exec_read(f"journalctl -u {name} -n {count} -q --no-pager")

    async def find_system_errors(self, hours: int = 1) -> Any:
        value = validate_hours_param(hours)
        return await self._exec_read(
            f"journalctl -p err --since '{value} hours ago' -q --no-pager -n {MAX_JOURNAL_LINES}"
        )

    async def search_journal_logs(self, term: str, lines: int = 50) -> Any:
        pattern = shlex.quote(validate_search_pattern(term))
        count = validate_lines_param(lines, MAX_JOURNAL_LINES)
        return await self._exec_read(
            f"journalctl -q --no-pager -n 5000 | grep -i -F -- {pattern} | tail -n {count}"
        )

    async def execute_program(
        self,
        executable: str,
        argv: list[str],
        cwd: str | None = None,
        stdin: str | None = None,
    ) -> Any:
        del executable, argv, cwd, stdin
        raise AppError(
            ErrorCode.UNAVAILABLE,
            "typed program execution is unavailable for the mikr.us API adapter",
        )

    async def remote_job_start(self, **_: object) -> Any:
        raise AppError(
            ErrorCode.UNAVAILABLE,
            "durable remote jobs are unavailable for the mikr.us API adapter",
        )

    async def remote_job_status(self, **_: object) -> Any:
        raise AppError(
            ErrorCode.UNAVAILABLE,
            "durable remote jobs are unavailable for the mikr.us API adapter",
        )

    async def remote_job_wait(self, **_: object) -> Any:
        raise AppError(
            ErrorCode.UNAVAILABLE,
            "durable remote jobs are unavailable for the mikr.us API adapter",
        )

    async def remote_job_result(self, **_: object) -> Any:
        raise AppError(
            ErrorCode.UNAVAILABLE,
            "durable remote jobs are unavailable for the mikr.us API adapter",
        )

    async def remote_job_output(self, **_: object) -> Any:
        raise AppError(
            ErrorCode.UNAVAILABLE,
            "durable remote jobs are unavailable for the mikr.us API adapter",
        )

    async def remote_job_cancel(self, **_: object) -> Any:
        raise AppError(
            ErrorCode.UNAVAILABLE,
            "durable remote jobs are unavailable for the mikr.us API adapter",
        )

    async def file_patch_atomic(self, **_: object) -> Any:
        raise AppError(
            ErrorCode.UNAVAILABLE,
            "atomic file patching is unavailable for the mikr.us API adapter",
        )

    async def cron_read(self, **_: object) -> Any:
        raise AppError(
            ErrorCode.UNAVAILABLE,
            "cron profile management is unavailable for the mikr.us API adapter",
        )

    async def cron_install(self, **_: object) -> Any:
        raise AppError(
            ErrorCode.UNAVAILABLE,
            "cron profile management is unavailable for the mikr.us API adapter",
        )

    async def docker_ps_filter(self, *, service: str, project: str | None = None) -> Any:
        del service, project
        raise AppError(
            ErrorCode.UNAVAILABLE,
            "docker compose management is unavailable for the mikr.us API adapter",
        )

    async def docker_inspect(self, ids: list[str]) -> Any:
        del ids
        raise AppError(
            ErrorCode.UNAVAILABLE,
            "docker compose management is unavailable for the mikr.us API adapter",
        )

    async def docker_compose_config(self, *, project: str, files: list[str]) -> Any:
        del project, files
        raise AppError(
            ErrorCode.UNAVAILABLE,
            "docker compose management is unavailable for the mikr.us API adapter",
        )

    async def docker_image_inspect(self, image: str) -> Any:
        del image
        raise AppError(
            ErrorCode.UNAVAILABLE,
            "docker compose management is unavailable for the mikr.us API adapter",
        )

    async def docker_compose_up(self, *, project: str, files: list[str], service: str) -> Any:
        del project, files, service
        raise AppError(
            ErrorCode.UNAVAILABLE,
            "docker compose management is unavailable for the mikr.us API adapter",
        )

    async def docker_service_wait(
        self, *, container_id: str, readiness: str, timeout_seconds: float
    ) -> Any:
        del container_id, readiness, timeout_seconds
        raise AppError(
            ErrorCode.UNAVAILABLE,
            "docker compose management is unavailable for the mikr.us API adapter",
        )

    @staticmethod
    def _parse_docker_jsonl(result: dict[str, Any]) -> dict[str, Any]:
        raw = str(result.get("output", ""))
        parsed: list[dict[str, Any]] = []
        for line in raw.splitlines():
            try:
                value = json.loads(html.unescape(line))
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                parsed.append(value)
        return {**result, "containers": parsed}
