"""Bounded SSH adapter with stable identity verification."""

from __future__ import annotations

import asyncio
import logging
import shlex
from typing import Any

from mikrus_mcp.clients.common import _remote_atomic_write_command, _remote_read_prefix
from mikrus_mcp.clients.mikrus import MikrusClient
from mikrus_mcp.config import TargetConfig
from mikrus_mcp.errors import AppError, ErrorCode
from mikrus_mcp.tools.constants import (
    EXEC_HTTP_TIMEOUT,
    MAX_JOURNAL_LINES,
    MAX_PROCESS_OUTPUT_BYTES,
    MAX_SEARCH_RESULTS,
    SSH_DEFAULT_TIMEOUT,
)
from mikrus_mcp.validators import (
    ValidationError,
    validate_container_name,
    validate_hours_param,
    validate_lines_param,
    validate_port,
    validate_process_target,
    validate_search_pattern,
    validate_service_action,
    validate_service_name,
)

logger = logging.getLogger(__name__)

SSH_TERMINATE_WAIT_SECONDS = 5.0


class SshClient:
    """AsyncSSH adapter which verifies host identity and bounds process output."""

    def __init__(self, config: TargetConfig) -> None:
        if config.type != "ssh" or config.host is None:
            raise ValueError("SshClient requires an SSH target configuration")
        self.config = config
        self.stable_identity = config.stable_identity
        self._connection: Any = None

    def __repr__(self) -> str:
        return f"SshClient(identity={self.stable_identity!r}, connected={self.is_connected})"

    @property
    def is_connected(self) -> bool:
        return self._connection is not None and not self._connection.is_closed()

    async def open(self) -> None:
        if self._connection is not None and not self._connection.is_closed():
            return
        if self._connection is not None:
            self._connection = None
        import asyncssh

        options: dict[str, Any] = {
            "host": self.config.host,
            "port": self.config.port,
            "username": self.config.user,
            "connect_timeout": self.config.connect_timeout_seconds,
            "login_timeout": self.config.connect_timeout_seconds,
        }
        if self.config.ssh_key:
            if self.config.ssh_cert:
                options["client_keys"] = [(str(self.config.ssh_key), str(self.config.ssh_cert))]
            else:
                options["client_keys"] = [str(self.config.ssh_key)]
        elif self.config.password:
            options["password"] = self.config.password
        if self.config.verify_host_key:
            if self.config.known_hosts_file:
                options["known_hosts"] = asyncssh.read_known_hosts(
                    str(self.config.known_hosts_file)
                )
        else:
            options["known_hosts"] = None
        connection = await asyncssh.connect(**options)
        try:
            if self.config.verify_host_key:
                host_key = connection.get_server_host_key()
                if host_key is None:
                    raise AppError(
                        ErrorCode.AUTHORIZATION,
                        "SSH server did not expose the verified host key",
                    )
                fingerprint = host_key.get_fingerprint("sha256")
                if not isinstance(fingerprint, str) or not fingerprint.startswith("SHA256:"):
                    raise AppError(
                        ErrorCode.AUTHORIZATION,
                        "SSH server host-key fingerprint is unavailable",
                    )
                self.stable_identity = f"{self.config.stable_identity}#host-key={fingerprint}"
            else:
                self.stable_identity = f"{self.config.stable_identity}#host-key=UNVERIFIED"
        except Exception:
            connection.close()
            wait_closed = getattr(connection, "wait_closed", None)
            if wait_closed is not None:
                await wait_closed()
            raise
        self._connection = connection

    async def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            wait_closed = getattr(self._connection, "wait_closed", None)
            if wait_closed is not None:
                await wait_closed()
            self._connection = None

    @staticmethod
    async def _terminate_process(process: Any) -> None:
        """Terminate, then escalate to close within bounded time so channels never leak."""
        terminate = getattr(process, "terminate", None)
        if callable(terminate):
            terminate()
        try:
            await asyncio.wait_for(process.wait(), SSH_TERMINATE_WAIT_SECONDS)
            return
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            process.close()
        try:
            await asyncio.wait_for(process.wait(), SSH_TERMINATE_WAIT_SECONDS)
        except asyncio.CancelledError:
            raise
        except (TimeoutError, OSError):
            logger.warning("SSH process channel did not close cleanly")

    async def _run(
        self, command: str, *, timeout: float | None = None, mutation: bool = False
    ) -> dict[str, Any]:
        if self._connection is None:
            raise AppError(ErrorCode.UNAVAILABLE, "SSH client is not open")
        limit = MAX_PROCESS_OUTPUT_BYTES
        process = await self._connection.create_process(command, encoding=None)
        total = 0
        total_lock = asyncio.Lock()

        async def collect(stream: Any) -> bytes:
            nonlocal total
            chunks: list[bytes] = []
            while True:
                chunk = await stream.read(65_536)
                if not chunk:
                    return b"".join(chunks)
                if isinstance(chunk, str):
                    encoded = chunk.encode("utf-8", errors="replace")
                else:
                    encoded = bytes(chunk)
                async with total_lock:
                    total += len(encoded)
                    if total > limit:
                        process.terminate()
                        raise AppError(ErrorCode.UPSTREAM, "SSH output exceeds size limit")
                chunks.append(encoded)

        seconds = float(timeout or self.config.connect_timeout_seconds or SSH_DEFAULT_TIMEOUT)
        try:
            async with asyncio.timeout(seconds):
                stdout, stderr = await asyncio.gather(
                    collect(process.stdout), collect(process.stderr)
                )
                await process.wait()
        except TimeoutError as exc:
            await self._terminate_process(process)
            code = ErrorCode.AMBIGUOUS if mutation else ErrorCode.TIMEOUT
            message = (
                "SSH mutation outcome is unknown after timeout; reconcile target state before retry"
                if mutation
                else f"SSH command exceeded {seconds:g} seconds"
            )
            raise AppError(code, message, retryable=False) from exc
        except asyncio.CancelledError:
            await self._terminate_process(process)
            raise
        return {
            "output": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "exit_code": int(process.exit_status),
        }

    async def _run_sudo(self, command: str, *, timeout: float | None = None) -> dict[str, Any]:
        if not self.config.sudo_password:
            return await self._run(command, timeout=timeout)
        if self._connection is None:
            raise AppError(ErrorCode.UNAVAILABLE, "SSH client is not open")
        process = await self._connection.create_process(
            f"sudo -S -- sh -c {shlex.quote(command)}", encoding=None
        )
        process.stdin.write((self.config.sudo_password + "\n").encode("utf-8"))
        await process.stdin.drain()
        process.stdin.write_eof()
        total = 0
        lock = asyncio.Lock()

        async def collect(stream: Any) -> bytes:
            nonlocal total
            chunks: list[bytes] = []
            while True:
                chunk = await stream.read(65_536)
                if not chunk:
                    return b"".join(chunks)
                data = chunk.encode() if isinstance(chunk, str) else bytes(chunk)
                async with lock:
                    total += len(data)
                    if total > MAX_PROCESS_OUTPUT_BYTES:
                        process.terminate()
                        raise AppError(ErrorCode.UPSTREAM, "SSH output exceeds size limit")
                chunks.append(data)

        seconds = float(timeout or self.config.connect_timeout_seconds)
        try:
            async with asyncio.timeout(seconds):
                stdout, stderr = await asyncio.gather(
                    collect(process.stdout), collect(process.stderr)
                )
                await process.wait()
        except TimeoutError as exc:
            await self._terminate_process(process)
            raise AppError(ErrorCode.TIMEOUT, "sudo command deadline exceeded") from exc
        except asyncio.CancelledError:
            await self._terminate_process(process)
            raise
        return {
            "output": stdout.decode(errors="replace"),
            "stderr": stderr.decode(errors="replace"),
            "exit_code": int(process.exit_status),
        }

    async def read_file(self, path: str) -> Any:
        return await self._run(
            _remote_read_prefix(path)
            + 'file -b --mime-encoding "$resolved" | grep -q binary && '
            + "echo 'ERROR: binary file' || head -n 200 -- \"$resolved\""
        )

    async def write_file(self, path: str, content: str) -> Any:
        command = _remote_atomic_write_command(path, content)
        return await self._run(command, timeout=EXEC_HTTP_TIMEOUT, mutation=True)

    async def get_service_status(self, name: str) -> Any:
        return await self._run(
            f"systemctl status --no-pager -- {shlex.quote(validate_service_name(name))}"
        )

    async def change_service_state(self, name: str, action: str) -> Any:
        action = validate_service_action(action)
        if action in {"status", "is-active", "is-enabled"}:
            raise ValidationError("read-only service actions use get_service_status")
        return await self._run(
            f"systemctl {action} -- {shlex.quote(validate_service_name(name))}", mutation=True
        )

    async def analyze_disk(self, path: str = "/") -> Any:
        return await self._run(
            _remote_read_prefix(path)
            + 'df -h -- "$resolved"; echo ---TOP20---; '
            + 'du -sh -- "$resolved"/* 2>/dev/null | sort -rh | head -n 20',
            timeout=30,
        )

    async def check_port(self, port: str) -> Any:
        value = validate_port(port)
        return await self._run(
            f"ss -tlnp 2>/dev/null | grep -F ':{value} ' || echo PORT_NOT_LISTENING"
        )

    async def list_processes(self) -> Any:
        return await self._run("ps aux --sort=-%mem | head -n 20")

    async def terminate_process(self, target: str) -> Any:
        value = shlex.quote(validate_process_target(target))
        if target.isdigit():
            return await self._run(f"kill -TERM -- {value}", mutation=True)
        return await self._run(f"pkill -TERM -x -- {value}", mutation=True)

    async def update_system(self) -> Any:
        return await self._run(
            "export DEBIAN_FRONTEND=noninteractive; apt-get update; "
            "apt-get upgrade -y -o Dpkg::Options::=--force-confdef "
            "-o Dpkg::Options::=--force-confold",
            timeout=120,
            mutation=True,
        )

    async def list_directory(self, path: str) -> Any:
        return await self._run(_remote_read_prefix(path) + 'ls -la -- "$resolved"')

    async def tail_file(self, path: str, lines: int = 50) -> Any:
        count = validate_lines_param(lines)
        return await self._run(_remote_read_prefix(path) + f'tail -n {count} -- "$resolved"')

    async def search_in_files(self, path: str, pattern: str) -> Any:
        term = shlex.quote(validate_search_pattern(pattern))
        return await self._run(
            _remote_read_prefix(path)
            + f'grep -r -F -n --max-count={MAX_SEARCH_RESULTS} -- {term} "$resolved" '
            + f"2>/dev/null | head -n {MAX_SEARCH_RESULTS}",
            timeout=30,
        )

    async def get_memory_info(self) -> Any:
        return await self._run("free -h")

    async def get_network_info(self) -> Any:
        return await self._run("ip addr; echo ---PORTS---; ss -tlnp")

    async def get_process_tree(self) -> Any:
        return await self._run("ps auxf | head -n 100")

    async def list_docker_containers(self) -> Any:
        return MikrusClient._parse_docker_jsonl(
            await self._run("docker ps -a --format '{{json .}}'")
        )

    async def get_docker_logs(self, container: str, lines: int = 50) -> Any:
        return await self._run(
            f"docker logs --tail {validate_lines_param(lines)} -- "
            f"{shlex.quote(validate_container_name(container))}"
        )

    async def get_docker_stats(self) -> Any:
        return MikrusClient._parse_docker_jsonl(
            await self._run("docker stats --no-stream --format '{{json .}}'")
        )

    async def get_journal_logs(self, unit: str, lines: int = 50) -> Any:
        return await self._run_sudo(
            f"journalctl -u {shlex.quote(validate_service_name(unit))} "
            f"-n {validate_lines_param(lines, MAX_JOURNAL_LINES)} -q --no-pager"
        )

    async def find_system_errors(self, hours: int = 1) -> Any:
        return await self._run_sudo(
            f"journalctl -p err --since '{validate_hours_param(hours)} hours ago' "
            f"-q --no-pager -n {MAX_JOURNAL_LINES}"
        )

    async def search_journal_logs(self, term: str, lines: int = 50) -> Any:
        return await self._run_sudo(
            f"journalctl -q --no-pager -n 5000 | grep -i -F -- "
            f"{shlex.quote(validate_search_pattern(term))} | "
            f"tail -n {validate_lines_param(lines, MAX_JOURNAL_LINES)}"
        )
