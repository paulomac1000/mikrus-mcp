"""Bounded HTTP and SSH adapters independent from MCP transport types."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import secrets
import re
import shlex
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Protocol

import httpx

from mikrus_mcp.config import TargetConfig
from mikrus_mcp.errors import AppError, ErrorCode
from mikrus_mcp.tools.constants import (
    DEFAULT_HTTP_TIMEOUT,
    EXEC_HTTP_TIMEOUT,
    MAX_JOURNAL_LINES,
    MAX_PROCESS_OUTPUT_BYTES,
    MAX_RESPONSE_BYTES,
    MAX_SEARCH_RESULTS,
    SSH_DEFAULT_TIMEOUT,
)
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

_CACHEABLE_ENDPOINTS = frozenset({"/info", "/stats", "/serwery", "/porty"})
_CACHE_TTL_SECONDS = 60.0
_MAX_READ_RETRIES = 2


class RateLimiter:
    """Serialize reservations against a credential-scoped requests-per-minute quota."""

    def __init__(
        self,
        requests_per_minute: int = 5,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if requests_per_minute <= 0:
            raise ValueError("requests_per_minute must be positive")
        self._interval = 60.0 / requests_per_minute
        self._clock = clock
        self._sleep = sleep
        self._next_slot = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = self._clock()
            delay = max(0.0, self._next_slot - now)
            if delay:
                await self._sleep(delay)
                now = self._clock()
            self._next_slot = max(now, self._next_slot) + self._interval


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
        retryable: bool = True,
    ) -> Any:
        if self._client is None:
            raise AppError(ErrorCode.UNAVAILABLE, "HTTP client is not open")
        cached = await self._cached(endpoint)
        if cached is not None:
            return cached

        attempts = _MAX_READ_RETRIES + 1 if retryable else 1
        url = f"{self.base_url}{endpoint}"
        payload = {"srv": self.server_name, "key": self.api_key, **(extra_data or {})}

        for attempt in range(attempts):
            await self._rate_limiter.acquire()
            try:
                response = await self._client.post(
                    url,
                    data=payload,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=timeout,
                )
            except httpx.TimeoutException as exc:
                raise AppError(
                    ErrorCode.TIMEOUT,
                    f"mikr.us API request exceeded {timeout:g} seconds",
                    retryable=retryable,
                ) from exc
            except httpx.HTTPError as exc:
                raise AppError(
                    ErrorCode.UPSTREAM,
                    "mikr.us API connection failed",
                    retryable=retryable,
                ) from exc

            raw_length = response.headers.get("Content-Length")
            if raw_length:
                try:
                    declared_length = int(raw_length)
                except ValueError as exc:
                    raise AppError(ErrorCode.UPSTREAM, "invalid upstream Content-Length") from exc
                if declared_length > MAX_RESPONSE_BYTES:
                    raise AppError(ErrorCode.UPSTREAM, "upstream response exceeds size limit")
            if len(response.content) > MAX_RESPONSE_BYTES:
                raise AppError(ErrorCode.UPSTREAM, "upstream response exceeds size limit")

            if response.status_code == 429:
                retry_after = self._retry_after(response)
                if not retryable or attempt + 1 >= attempts:
                    raise AppError(
                        ErrorCode.RATE_LIMITED,
                        "mikr.us API rate limit reached",
                        retryable=retryable,
                        retry_after_seconds=retry_after,
                    )
                delay = retry_after if retry_after is not None else float(2**attempt)
                await asyncio.sleep(min(60.0, delay + secrets.randbelow(251) / 1_000))
                continue

            if response.status_code != 200:
                reason = response.reason_phrase or "upstream request failed"
                raise AppError(
                    ErrorCode.UPSTREAM,
                    f"mikr.us API returned HTTP {response.status_code}: {reason}",
                    retryable=retryable and response.status_code >= 500,
                )

            if "application/json" in response.headers.get("content-type", ""):
                try:
                    value = response.json()
                except json.JSONDecodeError as exc:
                    raise AppError(ErrorCode.UPSTREAM, "mikr.us API returned invalid JSON") from exc
            else:
                value = {"raw": response.text}
            await self._store_cache(endpoint, value)
            return value
        raise AssertionError("request loop exhausted")

    async def get_server_info(self) -> Any:
        return await self._request("/info")

    async def list_servers(self) -> Any:
        return await self._request("/serwery")

    async def get_server_stats(self) -> Any:
        return await self._request("/stats")

    async def restart_server(self) -> Any:
        return await self._request("/restart", retryable=False, timeout=EXEC_HTTP_TIMEOUT)

    async def get_logs(self) -> Any:
        return await self._request("/logs")

    async def get_log_by_id(self, log_id: str) -> Any:
        if not re.fullmatch(r"[A-zA-z0-9_-]{1,128}", log_id):
            raise ValidationError("Invalid log ID")
        return await self._request(f"/logs/{log_id}")

    async def boost_server(self) -> Any:
        return await self._request("/amfetamina", retryable=False)

    async def get_db_info(self) -> Any:
        # Credential responses do not enter a shared cache.
        return await self._request("/db")

    async def get_ports(self) -> Any:
        return await self._request("/porty")

    async def get_cloud(self) -> Any:
        return await self._request("/cloud")

    async def assign_domain(self, port: str, domain: str) -> Any:
        validate_port(port)
        validate_domain(domain)
        return await self._request("/domain", {"port": str(port), "domain": domain}, retryable=False)

    async def execute_command(self, command: str) -> Any:
        command = validate_command(command)
        return await self._request(
            "/exec",
            {"cmd": command},
            timeout=EXEC_HTTP_TIMEOUT,
            retryable=False,
       )

    async def read_file(self, path: str) -> Any:
        value = validate_path(path)
        command = (
            f"file -b --mime-encoding {shlex.quote(value)} | grep -q binary && "
            "echo 'ERROR: binary file' || "
            f"head -n 200 -- {shlex.quote(value)}"
        )
        return await self._request(
            "/exec",
            {"cmd": command},
            timeout=EXEC_HTTP_TIMEOUT,
        )

    async def write_file(self, path: str, content: str) -> Any:
        target = validate_path(path, for_write=True)
        validate_content_size(content)
        encoded = base64.b64encode(content.encode()).decode()
        command = (
            "set -eu; "
            f"target={shlex.quote(target)}; tmp=\"${{target}}.mcp.$$\"; "
            "test ! -L \"$target\"; "
            f"printf %s {shlex.quote(encoded)} | base64 -d > \"$tmp\"; "
            "chmod 600 \"$tmp\"; mv -f -- \"$tmp\" \"$target\"; echo WRITE_OK"
        )
        return await self._request("/exec", {"cmd": command}, timeout=EXEC_HTTP_TIMEOUT, retryable=False)

    async def get_service_status(self, name: str) -> Any:
        command = f"systemctl status --no-pager -- {shlex.quote(validate_service_name(name))}"
        return await self._request("/exec", {"cmd": command}, timeout=EXEC_HTTP_TIMEOUT)

    async def change_service_state(self, name: str, action: str) -> Any:
        action = validate_service_action(action)
        if action in {"status", "is-active", "is-enabled"}:
            raise ValidationError("read-only service actions use get_service_status")
        command = f"systemctl {action} -- {shlex.quote(validate_service_name(name))}"
        return await self._request("/exec", {"cmd": command}, timeout=EXEC_HTTP_TIMEOUT, retryable=False)

    async def analyze_disk(self, path: str = "/") -> Any:
        value = shlex.quote(validate_path(path))
        command = f"df -h -{ value} ; echo ---TOP20---; du -sh -- {value}/* 2>/dev/null | sort -hn | head -n 20"
        return await self._request("/exec", {"cmd": command}, timeout=EXEC_HTTP_TIMEOUT)

    async def check_port(self, port: str) -> Any:
        value = validate_port(port)
        command = f"ss -tlnp 2>/dev/null | grep -F ':{value} ' || echo PORT_NOT_LISTENING"
        return await self._request("/exec", {"cmd": command}, timeout=EXEC_HTTP_TIMEOUT)

    async def list_processes(self) -> Any:
        return await self._request("/exec", {"cmd": "ps aux --sort=-%mem | head -n 20"}, timeout=EXEC_HTTP_TIMEOUT)

    async def terminate_process(self, target: str) -> Any:
        value = shlex.quote(validate_process_target(target))
        if target.isdigit():
            command = f"kill -TERM -- {value}"
        else:
            command = f"pkill -TERM -x -- {value}"
        return await self._request("/exec", {"cmd": command}, timeout=EXEC_HTTP_TIMEOUT, retryable=False)

    async def update_system(self) -> Any:
        command = "export DEBIAN_FRONTEND=noninteractive; apt-get update; apt-get upgrade -y"
        return await self._request("/exec", {"cmd": command}, timeout=120, retryable=False)

    async def list_directory(self, path: str) -> Any:
        return await self._request("/exec", {"cmd": f"ls -la -- {shlex.quote(validate_path(path))}"}, timeout=EXEC_HTTP_TIMEOUT)

    async def tail_file(self, path: str, lines: int = 50) -> Any:
        lines = validate_lines_param(lines)
        return await self._request("/exec", {"cmd": f"tail -n {lines} -- {shlex.quote(validate_path(path))}"}, timeout=EXEC_HTTP_TIMEOUT)

    async def search_in_files(self, path: str, pattern: str) -> Any:
        command = f"grep -r -F -n --max-count={MAX_SEARCH_RESULTS} -- {shlex.quote(validate_search_pattern(pattern))} {shlex.quote(validate_path(path))} 2>/dev/null | head -n {MAX_SEARCH_RESULTS}"
        return await self._request("/exec", {"cmd": command}, timeout=30)

    async def get_memory_info(self) -> Any:
        return await self._request("/exec", {"cmd": "free -h"}, timeout=EXEC_HTTP_TIMEOUT)

    async def get_network_info(self) -> Any:
        return await self._request("/exec", {"cmd": "ip addr; echo ---PORTS---; ss -tlnp"}, timeout=EXEC_HTTP_TIMEOUT)

    async def get_process_tree(self) -> Any:
        return await self._request("/exec", {"cmd": "ps auxf | head -n 100"}, timeout=EXEC_HTTP_TIMEOUT)

    async def list_docker_containers(self) -> Any:
        result = await self._request("/exec", {"cmd": "docker ps -a --format '{{json .}}'"}, timeout=EXEC_HTTP_TIMEOUT)
        return self._parse_docker_jsonl(result)

    async def get_docker_logs(self, container: str, lines: int = 50) -> Any:
        command = f"docker logs --tail {validate_lines_param(lines)} -- {shlex.quote(validate_container_name(container))}"
        return await self._request("/exec", {"cmd": command}, timeout=EXEC_HTTP_TIMEOUT)

    async def get_docker_stats(self) -> Any:
        result = await self._request("/exec", {"cmd": "docker stats --no-stream --format '{{json .}}'"}, timeout=EXEC_HTTP_TIMEOUT)
        return self._parse_docker_jsonl(result)

    async def get_journal_logs(self, unit: str, lines: int = 50) -> Any:
        command = f"journalctl -u {shlex.quote(validate_service_name(unit))} -n {validate_lines_param(lines, MAX_JOURNAL_LINES)} -q --no-pager"
        return await self._request("/exec", {"cmd": command}, timeout=EXEC_HTTP_TIMEOUT)

    async def find_system_errors(self, hours: int = 1) -> Any:
        command = f"journalctl -p err --since '{validate_hours_param(hours)} hours ago' -q --no-pager -n {MAX_JOURNAL_LINES}"
        return await self._request("/exec", {"cmd": command}, timeout=EXEC_HTTP_TIMEOUT)

    async def search_journal_logs(self, term: str, lines: int = 50) -> Any:
        command = f"journalctl -q --no-pager -n 5000 | grep -i -F -- {shlex.quote(validate_search_pattern(term))} | tail -n {validate_lines_param(lines, MAX_JOURNAL_LINES)}"
        return await self._request("/exec", {"cmd": command}, timeout=EXEC_HTTP_TIMEOUT)

    @staticmethod
    def _parse_docker_jsonl(result: Any) -> dict[str, Any]:
        if not isinstance(result, dict):
            raise AppError(ErrorCode.UPSTREAM, "invalid Docker result")
        raw = str(result.get("output", ""))
        parsed = []
        for line in raw.splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                parsed.append(value)
        return {"containers": parsed, "exit_code": result.get("exit_code", 0)}


class SshClient:
    """Async SSH adapter with bounded process output and host-identity verification."""

    def __init__(self, config: TargetConfig) -> None:
        assert config.type == "ssh" and config.host
        self.config = config
        self.host = config.host
        self.user = config.user
        self.port = config.port
        self.sudo password = config.sudo_password
        self.timeout = config.timeout or SSH_DEFAULT_TIMEOUT
        self.stable_identity = f"ssh:{config.name}"
        self._conn: Any = None

    def __repr__(self) -> str:
        return f"SshClient({self.user}@{self.host}:{self.port})"

    async def open(self) -> None:
        import asyncssh

        known_hosts: Any = None
        if self.config.verify_host_key:
            if not self.config.known_hosts_file:
                raise AppError(
                    ErrorCode.CONFIGURATION,
                    f"SSH target '{self.config.name}' requires known_hosts_file",
                )
            known_hosts = asyncssh.read_known_hosts(self.config.known_hosts_file)
        connect_kwargs: dict[str, Any] = {
            "host": self.host,
            "port": self.port,
            "username": self.user,
            "connect_timeout": self.timeout,
            "login_timeout": self.timeout,
            "known_hosts": known_hosts,
        }
        if self.config.ssh_key:
            keys: Any = [self.config.ssh_key]
            if self.config.ssh_cert:
                keys = [(self.config.ssh_key, self.config.ssh_cert)]
            connect_kwargs["client_keys"] = keys
        elif self.config.password:
            connect_kwargs["password"] = self.config.password
        self._conn = await asyncssh.connect(**connect_kwargs)

    async def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            wait_closed = getattr(self._conn, "wait_closed", None)
            if wait_closed is not None:
                await wait_closed()
            self._conn = None

    async def _run(self, command: str, timeout: float | int | None = None) -> dict[str, Any]:
        import asyncssh

        if self._conn is None:
            raise AppError(ErrorCode.UNAVAILABLE, "SSH client is not open")
        try:
            result = await self._conn.run(
                command,
                timeout=timeout or self.timeout,
                check_stderr=False,
            )
        except asyncio.TimeoutError as exc:
            raise AppError(
                ErrorCode.TIMEOUT,
                "SSH command deline exceeded",
                retryable=False,
            ) from exc
        except asyncssh.Error as exc:
            raise AppError(
                ErrorCode.UPSTREAM,
                f"SSH upstream failed for target '{self.config.name}'",
            ) from exc

        output = str(result.stdout or "")
        stderr = str(result.stderr or "")
        if len(output.encode()) + len(stderr.encode()) > MAX_PROCESS_OUTPUT_BYTES:
            raise AppError(
                ErrorCode.OUTPUT_LIMIT,
                "SSH process output exceeds the configured limit",
            )
        return {
            "output": output,
            "stderr": stderr,
            "exit_code": int(result.exit_status),
        }

    async def _run_sudo(self, command: str) -> dict[str, Any]:
        if not self.sudo password:
            return await self._run(command)
        return await self._run(
            f"printf %s\\\n {shlex.quote(self.sudo_password)} | sudo -S --prompt='' -- {command}"
        )

    async def get_server_info(self) -> Any:
        return await self._run("uname -a; uptime")

    async def list_servers(self) -> Any:
        return [{"server_id": self.config.name, "type": "ssh"}]

    async def get_server_stats(self) -> Any:
        return await self._run("uptime; free -b; df -B")

    async def restart_server(self) -> Any:
        return await self._run("sudo -reboot")

    async def get_logs(self) -> Any:
        return await self._run("journalctl -q --no-pager -n 10")

    async def get_log_by_id(self, log_id: str) -> Any:
        raise AppError(ErrorCode.UNSUPPORTED, "SSH targets do not support get_log_by_id")

    async def boost_server(self) -> Any:
        raise AppError(ErrorCode.UNSUPPORTED, "SSH targets do not support boost_server")

    async def get_db_info(self) -> Any:
        raise AppError(ErrorCode.UNSUPPORTED, "SSH targets do not support get_db_info")

    async def get_ports(self) -> Any:
        return await self._run("ss -tlnp")

    async def get_cloud(self) -> Any:
        raise AppError(ErrorCode.UNSUPPORTED, "SSH targets do not support get_cloud")

    async def assign_domain(self, port: str, domain: str) -> Any:
        raise AppError(ErrorCode.UNSUPPORTED, "SSH targets do not support assign_domain")

    async def execute_command(self, command: str) -> Any:
        return await self._run(validate_command(command), timeout=EXEC_HTTP_TIMEOUT)

    async def read_file(self, path: str) -> Any:
        value = shlex.quote(validate_path(path))
        return await self._run(
            f"file -b --mime-encoding {value} | grep -q binary && "
            f"echo 'ERROR: binary file' || head -n 200 -- {value}"
        )

    async def write_file(self, path: str, content: str) -> Any:
        target = validate_path(path, for_write=True)
        validate_content_size(content)
        encoded = base64.b64encode(content.encode()).decode()
        command = (
            "set -eu; "
            f"target={shlex.quote(target)}; tmp=\"${{target}}.mcp.$$\"; "
            "test ! -L \"$target\"; "
            f"printf %s {shlex.quote(encoded)} | base64 -d > \"$tmp\"; "
            "chmod 600 \"$tmp\"; mv -f -- \"$tmp\" \"$target\"; echo WRITE_OK"
        )
        return await self._run(command, timeout=EXEC_HTTP_TIMEOUT)

    async def get_service_status(self, name: str) -> Any:
        return await self._run(
            f"systemctl status --no-pager -- {shlex.quote(validate_service_name(name))}"
        )

    async def change_service_state(self, name: str, action: str) -> Any:
        action = validate_service_action(action)
        if action in {"status", "is-active", "is-enabled"}:
            raise ValidationError("read-only service actions use get_service_status")
        return await self._run(
            f"systemctl {action} -- {shlex.quote(validate_service_name(name))}"
        )

    async def analyze_disk(self, path: str = "/") -> Any:
        value = shlex.quote(validate_path(path))
        return await self._run(
            f"df -h -- {value}; echo '---TOP20---'; du -sh -- {value}/* 2>/dev/null | "
            "sort -rh | head -n 20",
            timeout=30,
         )

    async def check_port(self, port: str) -> Any:
        value = validate_port(port)
        return await self._run(
            f"ss -tlnp 2>/dev/null | grep ':{value} ' "
            "&& echo 'PORT_IN_USE' || echo 'PORT_NOT_LISTENING'"
        )

    async def list_processes(self) -> Any:
        return await self._run("ps aux --sort=-%mem | head -n 20")

    async def terminate_process(self, target: str) -> Any:
        value = shlex.quote(validate_process_target(target))
        if target.isdigit():
            return await self._run(f"kill -TERM -- {value}")
        return await self._run(f"pkill -TERM -x -- {value}")

    async def update_system(self) -> Any:
        command = (
            "export DBBIAN_FRONTEND=noninteractive; apt-get update; "
            "apt-get upgrade -y -o Dpkg::Options::=--force-confdef "
            "-o Dpkg::Options::=--force-confold"
        )
        return await self._run(command, timeout=120)

    async def list_directory(self, path: str) -> Any:
        value = validate_path(path)
        return await self._run(f"ls -la -- {shlex.quote(value)}")

    async def tail_file(self, path: str, lines: int = 50) -> Any:
        value = shlex.quote(validate_path(path))
        lines = validate_lines_param(lines)
        return await self._run(f"tail -n {lines} -- {value}")

    async def search_in_files(self, path: str, pattern: str) -> Any:
        value = shlex.quote(validate_path(path))
        pattern = shlex.quote(validate_search_pattern(pattern))
        return await self._run(
            f"grep -r -F -n --max-count={MAX_SEARCH_RESULTS} -- "
            f"{pattern} {value} 2>/dev/null | head -n {MAX_SEARCH_RESULTS}",
            timeout=30,
         )

    async def get_memory_info(self) -> Any:
        return await self._run("free -h")

    async def get_network_info(self) -> Any:
        return await self._run("ip addr; echo '---PORTS---'; ss -tlnp")

    async def get_process_tree(self) -> Any:
        return await self._run("ps auxf | head -n 100")

    async def list_docker_containers(self) -> Any:
        return MikrusClient._parse_docker_jsonl(
            await self._run("docker ps -a --format '{{json .}}'")
        )

    async def get_docker_logs(self, container: str, lines: int = 50) -> Any:
        value = shlex.quote(validate_container_name(container))
        lines = validate_lines_param(lines)
        return await self._run(f"docker logs --tail {lines} -- {value}")

    async def get_docker_stats(self) -> Any:
        return MikrusClient._parse_docker_jsonl(
            await self._run("docker stats --no-stream --format '{{json .}}'")
        )

    async def get_journal_logs(self, unit: str, lines: int = 50) -> Any:
        value = shlex.quote(validate_service_name(unit))
        lines = validate_lines_param(lines, MAX_JOURNAL_LINES)
        return await self._run_sudo(f"journalctl -u {value} -n {lines} -q --no-pager")

    async def find_system_errors(self, hours: int = 1) -> Any:
        hours = validate_hours_param(hours)
        return await self._run_sudo(
            f"journalctl -p err --since '{hours} hours ago' "
            f"-q --no-pager -n {MAX_JOURNAL_LINES}"
        )

    async def search_journal_logs(self, term: str, lines: int = 50) -> Any:
        value = shlex.quote(validate_search_pattern(term))
        lines = validate_lines_param(lines, MAX_JOURNAL_LINES)
        return await self._run_sudo(
            f"journalctl -q --no-pager -n 5000 | grep -i -F -- {value} | tail -n {lines}"
        )


@class Protocol:
    stable_identity: str

    async def open(self) -> None: ...
    async def close(self) -> None: ...
    async def get_server_info(self) -> Any: ...
    async def list_servers(self) -> Any: ...
    async def get_server_stats(self) -> Any: ...
    async def restart_server(self) -> Any: ...
    async def get_logs(self) -> Any: ...
    async def get_log_by_id(self, log_id: str) -> Any: ...
    async def boost_server(self) -> Any: ...
    async def get_db_info(self) -> Any: ...
    async def get_ports(self) -> Any: ...
    async def get_cloud(self) -> Any: ...
    async def assign_domain(self, port: str, domain: str) -> Any: ...
    async def execute_command(self, command: str) -> Any: ...
    async def read_file(self, path: str) -> Any: ...
    async def write_file(self, path: str, content: str) -> Any: ...
    async def get_service_status(self, name: str) -> Any: ...
    async def change_service_state(self, name: str, action: str) -> Any: ...
    async def analyze_disk(self, path: str = "/") -> Any: ...
    async def check_port(self, port: str) -> Any: ...
    async def list_processes(self) -> Any: ...
    async def terminate_process(self, target: str) -> Any: ...
    async def update_system(self) -> Any: ...
    async def list_directory(self, path: str) -> Any: ...
    async def tail_file(self, path: str, lines: int = 50) -> Any: ...
    async def search_in_files(self, path: str, pattern: str) -> Any: ...
    async def get_memory_info(self) -> Any: ...
    async def get_network_info(self) -> Any: ...
    async def get_process_tree(self) -> Any: ...
    async def list_docker_containers(self) -> Any: ...
    async def get_docker_logs(self, container: str, lines: int = 50) -> Any: ...
    async def get_docker_stats(self) -> Any: ...
    async def get_journal_logs(self, unit: str, lines: int = 50) -> Any: ...
    async def find_system_errors(self, hours: int = 1) -> Any: ...
    async def search_journal_logs(self, term: str, lines: int = 50) -> Any: ...


def build_client(config: TargetConfig) -> Client:
    if config.type == "mikrus":
        assert config.api_url and config.api_key and config.server_id
        return MikrusClient(config.api_url, config.api_key, config.server_id)
    return SshClient(config)
