"""HTTP and SSH clients for mikr.us API and remote servers."""

import asyncio
import base64
import json
import logging
import re
from pathlib import Path
from typing import Any

import httpx

from mikrus_mcp.validators import (
    MAX_JOURNAL_LINES,
    MAX_SEARCH_RESULTS,
    PROCESS_ACTIONS,
    ValidationError,
    check_dangerous_command,
    validate_container_name,
    validate_content_size,
    validate_domain,
    validate_hours_param,
    validate_lines_param,
    validate_path,
    validate_port,
    validate_search_pattern,
    validate_service_action,
    validate_service_name,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0
EXEC_TIMEOUT = 65.0
SSH_TIMEOUT = 30

PATH_PATTERN = re.compile(r"^[^\x00-\x1f\x7f]+$")
CONTAINER_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.\-]*$")


class MikrusClient:
    """Async HTTP client for the mikr.us API."""

    def __init__(self, base_url: str, api_key: str, server_name: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.server_name = server_name
        self._client: httpx.AsyncClient | None = None

    def __repr__(self) -> str:
        return f"MikrusClient(server={self.server_name}, url={self.base_url})"

    async def _request(
        self,
        endpoint: str,
        extra_data: dict[str, str] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> Any:
        """Send a POST request to the mikr.us API."""
        if self._client is None:
            raise RuntimeError("Client not opened. Use async context manager.")

        url = f"{self.base_url}{endpoint}"
        data = {
            "srv": self.server_name,
            "key": self.api_key,
            **(extra_data or {}),
        }

        try:
            response = await self._client.post(
                url,
                data=data,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=timeout,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            logger.error("Request to %s timed out after %ss", url, timeout)
            raise RuntimeError(f"Request timeout after {timeout}s") from exc
        except httpx.HTTPStatusError as exc:
            text = exc.response.text or exc.response.reason_phrase
            logger.error("HTTP error %s: %s", exc.response.status_code, text)
            raise RuntimeError(f"HTTP {exc.response.status_code}: {text}") from exc
        except httpx.HTTPError as exc:
            logger.error("HTTP error: %s", exc)
            raise RuntimeError(f"HTTP error: {exc}") from exc

        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                return response.json()
            except json.JSONDecodeError:
                logger.warning(
                    "Invalid JSON despite content-type header: %s",
                    response.text[:200],
                )
                return {"raw": response.text, "json_error": True}
        return {"raw": response.text}

    async def open(self) -> None:
        """Open the underlying HTTP client."""
        self._client = httpx.AsyncClient()
        logger.debug("HTTP client opened")

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.debug("HTTP client closed")

    async def __aenter__(self) -> "MikrusClient":
        await self.open()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    async def get_server_info(self) -> Any:
        """Get server information."""
        return await self._request("/info")

    async def get_server_stats(self) -> Any:
        """Get server statistics."""
        return await self._request("/stats")

    async def get_logs(self) -> Any:
        """Get last 10 logs."""
        return await self._request("/logs")

    async def get_log_by_id(self, log_id: str) -> Any:
        """Get a specific log entry by ID."""
        return await self._request(f"/logs/{log_id}")

    async def restart_server(self) -> Any:
        """Restart the server."""
        return await self._request("/restart")

    async def boost_server(self) -> Any:
        """Enable amfetamina (boost) on the server."""
        return await self._request("/amfetamina")

    async def execute_command(self, cmd: str) -> Any:
        """Execute a command on the server (60s API limit)."""
        check_dangerous_command(cmd)
        return await self._request("/exec", {"cmd": cmd}, timeout=EXEC_TIMEOUT)

    async def list_servers(self) -> Any:
        """List all servers associated with the account (cache=60s)."""
        return await self._request("/serwery")

    async def get_db_info(self) -> Any:
        """Get database access credentials (cache=60s)."""
        return await self._request("/db")

    async def get_ports(self) -> Any:
        """Get assigned TCP/UDP ports for the server (cache=60s)."""
        return await self._request("/porty")

    async def get_cloud(self) -> Any:
        """Get cloud services assigned to the account with statistics."""
        return await self._request("/cloud")

    async def assign_domain(self, port: str, domain: str) -> Any:
        """Assign a domain to a port. Use '-' for auto-generated subdomain."""
        validate_domain(domain)
        return await self._request("/domain", {"port": port, "domain": domain})

    async def read_file(self, path: str) -> Any:
        """Read a text file from the server. Limited to 200 lines."""
        validated = validate_path(path)
        cmd = f"cat '{validated}' 2>&1 | head -200"
        return await self._request("/exec", {"cmd": cmd}, timeout=EXEC_TIMEOUT)

    async def write_file(self, path: str, content: str) -> Any:
        """Write content to a file on the server. Uses base64 for safe transfer."""
        validated = validate_path(path, for_write=True)
        validate_content_size(content)
        encoded = base64.b64encode(content.encode()).decode()
        cmd = (
            f"echo '{encoded}' | base64 -d > '{validated}' && echo 'WRITE_OK' || echo 'WRITE_FAIL'"
        )
        return await self._request("/exec", {"cmd": cmd}, timeout=EXEC_TIMEOUT)

    async def manage_service(self, name: str, action: str) -> Any:
        """Manage a systemd service via systemctl."""
        validate_service_name(name)
        validate_service_action(action)
        cmd = f"systemctl {action} '{name}' 2>&1"
        return await self._request("/exec", {"cmd": cmd}, timeout=EXEC_TIMEOUT)

    async def analyze_disk(self, path: str = "/") -> Any:
        """Analyze disk usage. Shows df -h and top-20 directories by size."""
        if not path.startswith("/"):
            raise ValueError("Path must be absolute")
        validated = validate_path(path)
        cmd = (
            f"df -h '{validated}' 2>&1; echo '---TOP20---'; "
            f"du -sh '{validated}'/* 2>/dev/null | sort -rh | head -20"
        )
        return await self._request("/exec", {"cmd": cmd}, timeout=EXEC_TIMEOUT)

    async def check_port(self, port: str) -> Any:
        """Check if a TCP port is listening."""
        port_num = validate_port(port)
        cmd = (
            f"ss -tlnp 2>/dev/null | grep ':{port_num} ' && echo 'PORT_IN_USE' "
            f"|| echo 'PORT_NOT_LISTENING'"
        )
        return await self._request("/exec", {"cmd": cmd}, timeout=EXEC_TIMEOUT)

    async def manage_process(self, target: str, action: str) -> Any:
        """List or kill processes. Target can be PID or process name."""
        if action not in PROCESS_ACTIONS:
            raise ValidationError(f"Invalid action: {action}. Allowed: {sorted(PROCESS_ACTIONS)}")
        if action == "list":
            cmd = "ps aux --sort=-%mem 2>/dev/null | head -20"
        else:
            if not target:
                raise ValueError("target is required for kill action (PID or process name)")
            if not re.match(r"^[a-zA-Z0-9_\-]+$", target):
                raise ValueError(f"Invalid process target: {target}")
            cmd = f"killall -15 '{target}' 2>&1 || kill '{target}' 2>&1"
        return await self._request("/exec", {"cmd": cmd}, timeout=EXEC_TIMEOUT)

    async def update_system(self) -> Any:
        """Run apt update and apt upgrade on the server."""
        cmd = (
            "export DEBIAN_FRONTEND=noninteractive && "
            "apt-get update 2>&1 && "
            "apt-get upgrade -y -o Dpkg::Options::='--force-confdef' "
            "-o Dpkg::Options::='--force-confold' 2>&1"
        )
        return await self._request("/exec", {"cmd": cmd}, timeout=EXEC_TIMEOUT)

    async def list_directory(self, path: str) -> Any:
        """List directory contents (ls -la)."""
        validated = validate_path(path)
        cmd = f"ls -la -- '{validated}' 2>&1"
        return await self._request("/exec", {"cmd": cmd}, timeout=EXEC_TIMEOUT)

    async def tail_file(self, path: str, lines: int = 50) -> Any:
        """Read last N lines from a text file."""
        validated = validate_path(path)
        lines = validate_lines_param(lines)
        cmd = f"tail -n {lines} -- '{validated}' 2>&1"
        return await self._request("/exec", {"cmd": cmd}, timeout=EXEC_TIMEOUT)

    async def search_in_files(self, path: str, pattern: str) -> Any:
        """Search for a pattern in files under a path (grep -r)."""
        validated = validate_path(path)
        pattern = validate_search_pattern(pattern)
        cmd = (
            f"grep -r -F -n --max-count={MAX_SEARCH_RESULTS} "
            f"'{pattern}' '{validated}' 2>/dev/null | head -n {MAX_SEARCH_RESULTS}"
        )
        return await self._request("/exec", {"cmd": cmd}, timeout=EXEC_TIMEOUT)

    async def get_memory_info(self) -> Any:
        """Get memory usage information."""
        cmd = "free -h 2>&1"
        return await self._request("/exec", {"cmd": cmd}, timeout=EXEC_TIMEOUT)

    async def get_network_info(self) -> Any:
        """Get network interfaces and listening ports."""
        cmd = "ip addr 2>&1 && echo '---PORTS---' && ss -tlnp 2>&1"
        return await self._request("/exec", {"cmd": cmd}, timeout=EXEC_TIMEOUT)

    async def get_process_tree(self) -> Any:
        """Get process tree overview."""
        cmd = "ps auxf 2>&1 | head -100"
        return await self._request("/exec", {"cmd": cmd}, timeout=EXEC_TIMEOUT)

    async def list_docker_containers(self) -> Any:
        """List Docker containers."""
        cmd = "docker ps -a --format '{{json .}}' 2>&1"
        result = await self._request("/exec", {"cmd": cmd}, timeout=EXEC_TIMEOUT)
        return self._parse_docker_jsonl(result)

    async def get_docker_logs(self, container: str, lines: int = 50) -> Any:
        """Get logs from a Docker container."""
        validate_container_name(container)
        lines = validate_lines_param(lines)
        cmd = f"docker logs --tail {lines} '{container}' 2>&1"
        return await self._request("/exec", {"cmd": cmd}, timeout=EXEC_TIMEOUT)

    async def get_docker_stats(self) -> Any:
        """Get Docker container resource usage stats."""
        cmd = "docker stats --no-stream --format '{{json .}}' 2>&1"
        result = await self._request("/exec", {"cmd": cmd}, timeout=EXEC_TIMEOUT)
        return self._parse_docker_jsonl(result)

    @staticmethod
    def _parse_docker_jsonl(result: dict[str, Any]) -> dict[str, Any]:
        """Parse newline-separated JSON objects into a list."""
        raw = result.get("output", "")
        if not raw.strip():
            return result
        lines = [ln for ln in raw.strip().split("\n") if ln.strip()]
        parsed: list[dict[str, Any]] = []
        for line in lines:
            try:
                parsed.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return {"output": raw, "containers": parsed, "exit_code": result.get("exit_code", 0)}

    @staticmethod
    def _journal_access_hint(output: str) -> str | None:
        """Return a hint when journal access fails due to missing privileges."""
        low = output.lower()
        if "insufficient permissions" in low or "no journal files" in low:
            return (
                "Journal access denied — the API user lacks permissions to read "
                "systemd journal logs. Add the user to the 'systemd-journal' or "
                "'adm' group, or switch to an SSH server with 'sudo_password' "
                "configured."
            )
        return None

    async def get_journal_logs(self, unit: str, lines: int = 50) -> Any:
        """Get systemd journal logs for a unit."""
        validate_service_name(unit)
        lines = validate_lines_param(lines, MAX_JOURNAL_LINES)
        cmd = f"journalctl -u '{unit}' -n {lines} --no-pager 2>&1"
        result = await self._request("/exec", {"cmd": cmd}, timeout=EXEC_TIMEOUT)
        hint = self._journal_access_hint(result.get("output", ""))
        if hint:
            result["output"] = f"{result['output']}\n\n{hint}"
            result["requires_elevation"] = True
        return result

    async def find_system_errors(self, hours: int = 1) -> Any:
        """Find system errors in journal from the last N hours."""
        hours = validate_hours_param(hours)
        cmd = (
            f"journalctl -p err --since '{hours} hours ago' --no-pager -n {MAX_JOURNAL_LINES} 2>&1"
        )
        result = await self._request("/exec", {"cmd": cmd}, timeout=EXEC_TIMEOUT)
        hint = self._journal_access_hint(result.get("output", ""))
        if hint:
            result["output"] = f"{result['output']}\n\n{hint}"
            result["requires_elevation"] = True
        return result

    async def search_journal_logs(self, term: str, lines: int = 50) -> Any:
        """Search journal logs for a term."""
        validate_search_pattern(term)
        lines = validate_lines_param(lines, MAX_JOURNAL_LINES)
        cmd = f"journalctl -q --no-pager -n 5000 2>&1 | grep -i '{term}' | tail -n {lines}"
        result = await self._request("/exec", {"cmd": cmd}, timeout=EXEC_TIMEOUT)
        hint = self._journal_access_hint(result.get("output", ""))
        if hint:
            result["output"] = f"{result['output']}\n\n{hint}"
            result["requires_elevation"] = True
        return result


class SshClient:
    """Async SSH client for executing commands on remote Linux servers."""

    def __init__(
        self,
        host: str,
        user: str = "root",
        port: int = 22,
        ssh_key: str | None = None,
        ssh_cert: str | None = None,
        password: str | None = None,
        sudo_password: str | None = None,
        timeout: int = SSH_TIMEOUT,
        verify_host_key: bool = False,
        known_hosts_file: str | None = None,
    ) -> None:
        self.host = host
        self.user = user
        self.port = port
        self.ssh_key = ssh_key
        self.ssh_cert = ssh_cert
        self.password = password
        self.sudo_password = sudo_password
        self.timeout = timeout
        self.verify_host_key = verify_host_key
        self.known_hosts_file = known_hosts_file
        self._conn: Any = None

    def __repr__(self) -> str:
        return f"SshClient({self.user}@{self.host}:{self.port}, connected={self.is_connected})"

    @property
    def is_connected(self) -> bool:
        return (
            self._conn is not None
            and not self._conn.is_closed()
            and getattr(self._conn, "_transport", None) is not None
        )

    async def _run(self, cmd: str, timeout: float | int | None = None) -> dict[str, Any]:
        """Execute a command via SSH and return structured result."""
        import asyncssh

        if self._conn is None:
            raise RuntimeError("SSH client not opened. Use async context manager.")

        try:
            result = await self._conn.run(cmd, timeout=timeout or self.timeout)
            return {
                "output": result.stdout or "",
                "stderr": result.stderr or "",
                "exit_code": result.exit_status,
            }
        except asyncssh.Error as exc:
            logger.error("SSH error on %s: %s", self.host, exc)
            raise RuntimeError(f"SSH error: {exc}") from exc

    async def _run_with_sudo(self, cmd: str) -> dict[str, Any]:
        """Execute a command via SSH with sudo -S, feeding password via stdin."""
        import asyncssh

        if self._conn is None:
            raise RuntimeError("SSH client not opened. Use async context manager.")

        if not self.sudo_password:
            return await self._run(cmd)

        try:
            process = await self._conn.create_process(
                f"sudo -S {cmd}",
                stdin=asyncssh.PIPE,
            )
            process.stdin.write(f"{self.sudo_password}\n")
            await process.stdin.drain()
            process.stdin.write_eof()

            stdout_lines: list[str] = []
            stderr_lines: list[str] = []

            async def _collect() -> None:
                async for line in process.stdout:
                    stdout_lines.append(line)
                async for line in process.stderr:
                    stderr_lines.append(line)

            await asyncio.wait_for(_collect(), timeout=self.timeout + 10)
            await process.wait()

            return {
                "output": "".join(stdout_lines),
                "stderr": "".join(stderr_lines),
                "exit_code": process.exit_status,
            }
        except asyncssh.Error as exc:
            logger.error("SSH error on %s: %s", self.host, exc)
            raise RuntimeError(f"SSH error: {exc}") from exc

    async def open(self) -> None:
        """Open SSH connection."""
        import asyncssh

        connect_kwargs: dict[str, Any] = {
            "host": self.host,
            "port": self.port,
            "username": self.user,
            "connect_timeout": self.timeout,
            "login_timeout": self.timeout,
        }
        if self.ssh_key and Path(self.ssh_key).exists():
            if self.ssh_cert and Path(self.ssh_cert).exists():
                connect_kwargs["client_keys"] = [(self.ssh_key, self.ssh_cert)]
            else:
                connect_kwargs["client_keys"] = [self.ssh_key]
        elif self.password:
            connect_kwargs["password"] = self.password

        if self.verify_host_key:
            if self.known_hosts_file:
                connect_kwargs["known_hosts"] = asyncssh.read_known_hosts(self.known_hosts_file)
            else:
                connect_kwargs["known_hosts"] = ()
        else:
            connect_kwargs["known_hosts"] = None
            logger.warning(
                "SSH host key verification DISABLED for %s — MITM risk!",
                self.host,
            )

        self._conn = await asyncssh.connect(**connect_kwargs)
        logger.debug("SSH connected to %s@%s", self.user, self.host)

    async def close(self) -> None:
        """Close SSH connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
            logger.debug("SSH disconnected from %s", self.host)

    async def __aenter__(self) -> "SshClient":
        await self.open()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    async def execute_command(self, cmd: str) -> Any:
        """Execute a shell command."""
        check_dangerous_command(cmd)
        return await self._run(cmd)

    async def read_file(self, path: str) -> Any:
        """Read a text file."""
        validated = validate_path(path)
        return await self._run(f"cat '{validated}' 2>&1 | head -200")

    async def write_file(self, path: str, content: str) -> Any:
        """Write content to a file."""
        validated = validate_path(path, for_write=True)
        validate_content_size(content)
        encoded = base64.b64encode(content.encode()).decode()
        cmd = (
            f"echo '{encoded}' | base64 -d > '{validated}' && echo 'WRITE_OK' || echo 'WRITE_FAIL'"
        )
        return await self._run(cmd)

    async def manage_service(self, name: str, action: str) -> Any:
        """Manage a systemd service."""
        validate_service_name(name)
        validate_service_action(action)
        return await self._run(f"systemctl {action} '{name}' 2>&1")

    async def analyze_disk(self, path: str = "/") -> Any:
        """Analyze disk usage."""
        if not path.startswith("/"):
            raise ValueError("Path must be absolute")
        validated = validate_path(path)
        cmd = (
            f"df -h '{validated}' 2>&1; echo '---TOP20---'; "
            f"du -sh '{validated}'/* 2>/dev/null | sort -rh | head -20"
        )
        return await self._run(cmd, timeout=EXEC_TIMEOUT)

    async def check_port(self, port: str) -> Any:
        """Check if a TCP port is listening."""
        port_num = validate_port(port)
        cmd = (
            f"ss -tlnp 2>/dev/null | grep ':{port_num} ' "
            "&& echo 'PORT_IN_USE' || echo 'PORT_NOT_LISTENING'"
        )
        return await self._run(cmd)

    async def manage_process(self, target: str, action: str) -> Any:
        """List or kill processes."""
        if action not in PROCESS_ACTIONS:
            raise ValueError(f"Invalid action: {action}")
        if action == "list":
            cmd = "ps aux --sort=-%mem 2>/dev/null | head -20"
        else:
            if not target:
                raise ValueError("target is required for kill action")
            if not re.match(r"^[a-zA-Z0-9_\-]+$", target):
                raise ValueError(f"Invalid process target: {target}")
            cmd = f"killall -15 '{target}' 2>&1 || kill '{target}' 2>&1"
        return await self._run(cmd)

    async def update_system(self) -> Any:
        """Run system updates."""
        cmd = (
            "export DEBIAN_FRONTEND=noninteractive && "
            "apt-get update 2>&1 && "
            "apt-get upgrade -y -o Dpkg::Options::='--force-confdef' "
            "-o Dpkg::Options::='--force-confold' 2>&1"
        )
        return await self._run(cmd)

    async def list_directory(self, path: str) -> Any:
        """List directory contents (ls -la)."""
        validated = validate_path(path)
        return await self._run(f"ls -la -- '{validated}' 2>&1")

    async def tail_file(self, path: str, lines: int = 50) -> Any:
        """Read last N lines from a text file."""
        validated = validate_path(path)
        lines = validate_lines_param(lines)
        return await self._run(f"tail -n {lines} -- '{validated}' 2>&1")

    async def search_in_files(self, path: str, pattern: str) -> Any:
        """Search for a pattern in files under a path (grep -r)."""
        validated = validate_path(path)
        pattern = validate_search_pattern(pattern)
        cmd = (
            f"grep -r -F -n --max-count={MAX_SEARCH_RESULTS} "
            f"'{pattern}' '{validated}' 2>/dev/null | head -n {MAX_SEARCH_RESULTS}"
        )
        return await self._run(cmd)

    async def get_memory_info(self) -> Any:
        """Get memory usage information."""
        return await self._run("free -h 2>&1")

    async def get_network_info(self) -> Any:
        """Get network interfaces and listening ports."""
        return await self._run("ip addr 2>&1 && echo '---PORTS---' && ss -tlnp 2>&1")

    async def get_process_tree(self) -> Any:
        """Get process tree overview."""
        return await self._run("ps auxf 2>&1 | head -100")

    async def list_docker_containers(self) -> Any:
        """List Docker containers."""
        result = await self._run("docker ps -a --format '{{json .}}' 2>&1")
        return self._parse_docker_jsonl(result)

    async def get_docker_logs(self, container: str, lines: int = 50) -> Any:
        """Get logs from a Docker container."""
        validate_container_name(container)
        lines = validate_lines_param(lines)
        return await self._run(f"docker logs --tail {lines} '{container}' 2>&1")

    async def get_docker_stats(self) -> Any:
        """Get Docker container resource usage stats."""
        result = await self._run("docker stats --no-stream --format '{{json .}}' 2>&1")
        return self._parse_docker_jsonl(result)

    @staticmethod
    def _parse_docker_jsonl(result: dict[str, Any]) -> dict[str, Any]:
        """Parse newline-separated JSON objects into a list."""
        raw = result.get("output", "")
        if not raw.strip():
            return result
        lines = [ln for ln in raw.strip().split("\n") if ln.strip()]
        parsed: list[dict[str, Any]] = []
        for line in lines:
            try:
                parsed.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return {
            "output": raw,
            "containers": parsed,
            "exit_code": result.get("exit_code", 0),
            "stderr": result.get("stderr", ""),
        }

    def _journal_access_hint(self, output: str) -> str | None:
        """Return a hint when journal access fails due to missing privileges."""
        low = output.lower()
        if "insufficient permissions" in low or "no journal files" in low:
            if not self.sudo_password:
                return (
                    "Journal access denied — the user lacks permissions to read "
                    "systemd journal logs. To fix this, add 'sudo_password' to the "
                    "SSH server configuration in MIKRUS_SERVERS (e.g. "
                    '"sudo_password": "yourpassword").'
                )
        return None

    async def get_journal_logs(self, unit: str, lines: int = 50) -> Any:
        """Get systemd journal logs for a unit."""
        validate_service_name(unit)
        lines = validate_lines_param(lines, MAX_JOURNAL_LINES)
        cmd = f"journalctl -u '{unit}' -n {lines} -q --no-pager"
        result = await self._run_with_sudo(cmd)
        hint = self._journal_access_hint(result.get("output", ""))
        if hint:
            result["output"] = f"{result['output']}\n\n{hint}"
            result["requires_elevation"] = True
        return result

    async def find_system_errors(self, hours: int = 1) -> Any:
        """Find system errors in journal from the last N hours."""
        hours = validate_hours_param(hours)
        cmd = f"journalctl -p err --since '{hours} hours ago' -q --no-pager -n {MAX_JOURNAL_LINES}"
        result = await self._run_with_sudo(cmd)
        hint = self._journal_access_hint(result.get("output", ""))
        if hint:
            result["output"] = f"{result['output']}\n\n{hint}"
            result["requires_elevation"] = True
        return result

    async def search_journal_logs(self, term: str, lines: int = 50) -> Any:
        """Search journal logs for a term."""
        validate_search_pattern(term)
        lines = validate_lines_param(lines, MAX_JOURNAL_LINES)
        cmd = f"journalctl -q --no-pager -n 5000 | grep -i '{term}' | tail -n {lines}"
        result = await self._run_with_sudo(cmd)
        hint = self._journal_access_hint(result.get("output", ""))
        if hint:
            result["output"] = f"{result['output']}\n\n{hint}"
            result["requires_elevation"] = True
        return result
