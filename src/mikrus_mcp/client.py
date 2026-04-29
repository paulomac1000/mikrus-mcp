"""HTTP client for mikr.us API."""

import base64
import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0
EXEC_TIMEOUT = 65.0

PATH_PATTERN = re.compile(r"^[a-zA-Z0-9_./\-]+$")
SERVICE_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_\-@.]+$")
SERVICE_ACTIONS = frozenset(
    {"status", "start", "stop", "restart", "enable", "disable", "is-active", "is-enabled"}
)
PROCESS_ACTIONS = frozenset({"list", "kill"})


class MikrusClient:
    """Async HTTP client for the mikr.us API."""

    def __init__(self, base_url: str, api_key: str, server_name: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.server_name = server_name
        self._client: httpx.AsyncClient | None = None

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
            return response.json()
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
        """Assign a domain to a port. Use '-' for domain to let the system auto-assign one."""
        return await self._request("/domain", {"port": port, "domain": domain})

    async def read_file(self, path: str) -> Any:
        """Read a text file from the server. Limited to 200 lines."""
        if not PATH_PATTERN.match(path) or ".." in path:
            raise ValueError(f"Invalid path: {path}")
        cmd = f"cat '{path}' 2>&1 | head -200"
        return await self._request("/exec", {"cmd": cmd}, timeout=EXEC_TIMEOUT)

    async def write_file(self, path: str, content: str) -> Any:
        """Write content to a file on the server. Uses base64 for safe transfer."""
        if not PATH_PATTERN.match(path) or ".." in path:
            raise ValueError(f"Invalid path: {path}")
        encoded = base64.b64encode(content.encode()).decode()
        cmd = f"echo '{encoded}' | base64 -d > '{path}' && echo 'WRITE_OK' || echo 'WRITE_FAIL'"
        return await self._request("/exec", {"cmd": cmd}, timeout=EXEC_TIMEOUT)

    async def manage_service(self, name: str, action: str) -> Any:
        """Manage a systemd service via systemctl."""
        if not SERVICE_NAME_PATTERN.match(name):
            raise ValueError(f"Invalid service name: {name}")
        if action not in SERVICE_ACTIONS:
            raise ValueError(f"Invalid action: {action}. Allowed: {sorted(SERVICE_ACTIONS)}")
        cmd = f"systemctl {action} '{name}' 2>&1"
        return await self._request("/exec", {"cmd": cmd}, timeout=EXEC_TIMEOUT)

    async def analyze_disk(self, path: str = "/") -> Any:
        """Analyze disk usage. Shows df -h and top-20 directories by size."""
        if not path.startswith("/"):
            raise ValueError("Path must be absolute")
        cmd = (
            f"df -h '{path}' 2>&1; echo '---TOP20---'; "
            "du -sh /* 2>/dev/null | sort -rh | head -20"
        )
        return await self._request("/exec", {"cmd": cmd}, timeout=EXEC_TIMEOUT)

    async def check_port(self, port: str) -> Any:
        """Check if a TCP port is listening."""
        port_num = int(port)
        if port_num < 1 or port_num > 65535:
            raise ValueError(f"Invalid port: {port}")
        cmd = (
            f"ss -tlnp 2>/dev/null | grep ':({port}) ' && echo 'PORT_IN_USE' "
            f"|| echo 'PORT_NOT_LISTENING'"
        )
        return await self._request("/exec", {"cmd": cmd}, timeout=EXEC_TIMEOUT)

    async def manage_process(self, target: str, action: str) -> Any:
        """List or kill processes. Target can be PID or process name."""
        if action not in PROCESS_ACTIONS:
            raise ValueError(f"Invalid action: {action}. Allowed: list, kill")
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
        cmd = "apt update 2>&1 && apt upgrade -y 2>&1"
        return await self._request("/exec", {"cmd": cmd}, timeout=EXEC_TIMEOUT)
