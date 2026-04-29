"""HTTP client for mikr.us API."""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0
EXEC_TIMEOUT = 65.0


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
