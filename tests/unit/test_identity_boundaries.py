from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from mikrus_mcp.approvals import ApprovalRegistry, normalized_arguments_digest
from mikrus_mcp.config import Settings, TargetConfig
from mikrus_mcp.http import AUTH_SCOPE_KEY
from mikrus_mcp.kernel import CallerContext, InvocationKernel
from mikrus_mcp.targets import TargetRegistry
from mikrus_mcp.tool_common import _caller


class MockClient:
    def __init__(self, config: TargetConfig) -> None:
        self.stable_identity = config.stable_identity
        self.calls: list[tuple[str, str]] = []

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def write_file(self, path: str, content: str) -> dict[str, str]:
        self.calls.append((path, content))
        return {"output": "ok"}


@pytest.mark.asyncio
async def test_kernel_rejects_alias_bound_approval_and_accepts_stable_identity() -> None:
    target = TargetConfig(
        "prod", "mikrus", api_url="https://api.mikr.us", api_key="k", server_id="srv-a"
    )
    settings = Settings(
        {"prod": target},
        "prod",
        write_enabled=True,
        allowed_scopes=frozenset({"tool:*", "target:*", "write:server"}),
    )
    client = MockClient(target)
    registry = TargetRegistry({"prod": target}, factory=lambda _: client)  # type: ignore[arg-type]
    approvals = ApprovalRegistry()
    arguments = {"path": "/tmp/a", "content": "x"}
    digest = normalized_arguments_digest(arguments)
    approvals.issue("write_file", "principal", "prod", "/tmp/a", digest)
    denied = await InvocationKernel(settings, registry=registry, approvals=approvals).invoke(
        "write_file", arguments, CallerContext("principal", settings.allowed_scopes)
    )
    assert denied["error"]["code"] == "AUTHORIZATION_FAILED"
    assert not client.calls

    approvals.issue("write_file", "principal", target.stable_identity, "/tmp/a", digest)
    allowed = await InvocationKernel(settings, registry=registry, approvals=approvals).invoke(
        "write_file", arguments, CallerContext("principal", settings.allowed_scopes)
    )
    assert allowed["success"] is True
    assert client.calls == [("/tmp/a", "x")]


def _http_context(settings: Settings, auth: object) -> Any:
    request = SimpleNamespace(scope={AUTH_SCOPE_KEY: auth})
    request_context = SimpleNamespace(
        lifespan_context=SimpleNamespace(settings=settings), request=request
    )
    return SimpleNamespace(request_context=request_context)


def test_http_caller_uses_request_identity_not_process_identity() -> None:
    target = TargetConfig(
        "prod", "mikrus", api_url="https://api.mikr.us", api_key="k", server_id="srv"
    )
    settings = Settings(
        {"prod": target},
        "prod",
        transport="streamable-http",
        http_bearer_token="x" * 48,
        principal="wrong-process-principal",
        allowed_scopes=frozenset({"tool:*"}),
    )
    caller = _caller(
        _http_context(
            settings,
            {"principal": "request-principal", "scopes": ("target:prod",)},
        )
    )
    assert caller.principal == "request-principal"
    assert caller.scopes == frozenset({"target:prod"})


def test_http_caller_fails_closed_without_authenticated_request_context() -> None:
    target = TargetConfig(
        "prod", "mikrus", api_url="https://api.mikr.us", api_key="k", server_id="srv"
    )
    settings = Settings(
        {"prod": target},
        "prod",
        transport="streamable-http",
        http_bearer_token="x" * 48,
    )
    with pytest.raises(ToolError, match="authenticated HTTP principal is missing"):
        _caller(_http_context(settings, None))


def test_operator_cli_resolves_server_alias_to_stable_identity(tmp_path: Path) -> None:
    path = tmp_path / "approvals.json"
    root = Path(__file__).resolve().parents[2]
    env = dict(os.environ)
    env["MCP_SERVERS"] = json.dumps(
        {
            "prod": {
                "type": "mikrus",
                "key": "test-key",
                "srv": "srv-123",
                "api_url": "https://api.mikr.us",
            }
        }
    )
    env["MCP_DEFAULT_SERVER"] = "prod"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/approval.py",
            "--file",
            str(path),
            "--capability",
            "write_file",
            "--principal",
            "operator",
            "--server",
            "prod",
            "--resource",
            "/tmp/a",
            "--arguments-json",
            '{"path":"/tmp/a","content":"x"}',
            "--ttl-seconds",
            "60",
        ],
        cwd=root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    issued = json.loads(completed.stdout)
    assert issued["target_identity"] == "mikrus:srv-123"
    registry = ApprovalRegistry.from_file(path)
    assert registry.consume_matching(
        "write_file",
        "operator",
        "mikrus:srv-123",
        "/tmp/a",
        normalized_arguments_digest({"path": "/tmp/a", "content": "x"}),
    )
