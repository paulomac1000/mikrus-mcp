from __future__ import annotations

import pytest

from mikrus_mcp.approvals import ApprovalRegistry
from mikrus_mcp.config import Settings, TargetConfig
from mikrus_mcp.kernel import CallerContext, InvocationKernel
from mikrus_mcp.targets import TargetRegistry


class MockClient:
    def __init__(self, config: TargetConfig) -> None:
        self.stable_identity = config.stable_identity

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def get_server_info(self) -> dict[str, object]:
        return {
            "server_id": "abc123",
            "imie_id": "abc123",
            "server_name": None,
            "expires": "2027-02-13 00:00:00",
            "expires_storage": None,
            "param_ram": "1024",
            "param_disk": "15",
            "lastlog_panel": "2026-07-08 00:21:18",
            "mikrus_pro": "nie",
        }


@pytest.mark.asyncio
async def test_application_kernel_invokes_mocked_backend_and_zero_io_catalog() -> None:
    target = TargetConfig(
        "srv", "mikrus", api_url="https://api.mikr.us", api_key="k", server_id="srv"
    )
    settings = Settings(
        {"srv": target},
        "srv",
        allowed_scopes=frozenset(
            {"tool:*", "target:*", "target-id:*", "resource:*", "data:*", "write:server"}
        ),
    )
    registry = TargetRegistry(
        {"srv": target},
        factory=lambda value: MockClient(value),  # type: ignore[arg-type]
    )
    kernel = InvocationKernel(settings, registry=registry, approvals=ApprovalRegistry())
    caller = CallerContext("principal", settings.allowed_scopes)

    result = await kernel.invoke("get_server_info", {}, caller)
    assert result["data"]["param_ram"] == "1024"
    assert result["data"]["mikrus_pro"] == "nie"

    capabilities = await kernel.invoke("describe_mikrus_capabilities", {}, caller)
    assert capabilities["data"]["supported_transports"] == ["stdio", "streamable-http"]
    await kernel.close()
