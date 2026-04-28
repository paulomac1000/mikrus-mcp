"""Client for mikr.us API."""

import httpx


class MikrusAPI:
    """Client for mikr.us API."""

    def __init__(self, client: httpx.AsyncClient, api_key: str, base_url: str):
        self.client = client
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def get_server_info(self) -> str:
        """Get server information."""
        try:
            response = await self.client.get(
                f"{self.base_url}/info",
                headers=self._headers(),
            )
            response.raise_for_status()
            data = response.json()
            return f"Server info:\n{data}"
        except httpx.HTTPError as e:
            return f"Error fetching server info: {e}"

    async def get_server_logs(self, lines: int = 50) -> str:
        """Get server logs."""
        try:
            response = await self.client.get(
                f"{self.base_url}/logs",
                headers=self._headers(),
                params={"lines": lines},
            )
            response.raise_for_status()
            data = response.text
            return f"Server logs (last {lines} lines):\n{data}"
        except httpx.HTTPError as e:
            return f"Error fetching server logs: {e}"

    async def restart_server(self) -> str:
        """Restart the server."""
        try:
            response = await self.client.post(
                f"{self.base_url}/restart",
                headers=self._headers(),
            )
            response.raise_for_status()
            return "Server restart initiated successfully."
        except httpx.HTTPError as e:
            return f"Error restarting server: {e}"

    async def enable_amfetamina(self) -> str:
        """Enable 'amfetamina' (boost) on the server."""
        try:
            response = await self.client.post(
                f"{self.base_url}/amfetamina",
                headers=self._headers(),
            )
            response.raise_for_status()
            return "Amfetamina enabled successfully."
        except httpx.HTTPError as e:
            return f"Error enabling amfetamina: {e}"

    async def check_port(self, port: int) -> str:
        """Check if a port is open."""
        try:
            response = await self.client.get(
                f"{self.base_url}/port/{port}",
                headers=self._headers(),
            )
            response.raise_for_status()
            data = response.json()
            return f"Port {port} check result:\n{data}"
        except httpx.HTTPError as e:
            return f"Error checking port {port}: {e}"
