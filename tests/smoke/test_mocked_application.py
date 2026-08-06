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
        return {"server_id": "srv", "status": "mocked"}


@pytest.mark.asyncio
async def test_application_kernel_invokes_mocked_backend_and_zero_io_catalog() -> None:
    target = TargetConfig(
        "srv", "mikrus", api_url="https://api.mikr.us", api_key="k", server_id="srv"
    )
    settings = Settings(
        {"srv": target},
        "srv",
        allowed_scopes=frozenset({"tool:*", "target:*", "write:server"}),
    )
    registry = TargetRegistry(
        {"srv": target},
        factory=lambda value: MockClient(value),  # type: ignore[arg-type]
    )
    kernel = InvocationKernel(settings, registry=registry, approvals=ApprovalRegistry())
    caller = CallerContext("principal", settings.allowed_scopes)

    result = await kernel.invoke("get_server_info", {}, caller)
    assert result["data"] == {"server_id": "srv", "status": "mocked"}

    capabilities = await kernel.invoke("describe_mikrus_capabilities", {}, caller)
    assert capabilities["data"]["supported_transports"] == ["stdio", "streamable-http"]
    await kernel.close()
