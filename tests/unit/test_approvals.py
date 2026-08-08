from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from mikrus_mcp.approvals import ApprovalRegistry, normalized_arguments_digest


def digest(arguments: dict[str, object]) -> str:
    return normalized_arguments_digest(arguments)


def write_digest(content: str = "x") -> str:
    return digest({"path": "/tmp/a", "content": content})


def test_approval_is_bound_and_single_use() -> None:
    registry = ApprovalRegistry()
    approved = write_digest()
    token = registry.issue_for_test("write_file", "principal", "prod", "/tmp/a", approved)
    assert not registry.consume(token, "write_file", "principal", "other", "/tmp/a", approved)
    assert registry.consume(token, "write_file", "principal", "prod", "/tmp/a", approved)


def test_same_resource_changed_arguments_is_rejected_without_consumption() -> None:
    registry = ApprovalRegistry()
    approved = write_digest("approved")
    changed = write_digest("changed")
    token = registry.issue_for_test("write_file", "principal", "prod", "/tmp/a", approved)
    assert not registry.consume(token, "write_file", "principal", "prod", "/tmp/a", changed)
    assert registry.consume(token, "write_file", "principal", "prod", "/tmp/a", approved)


def test_digest_binds_operation_but_not_public_target_selector() -> None:
    first = digest({"server": "prod", "path": "/tmp/a", "content": "x"})
    second = digest({"server": "backup", "path": "/tmp/a", "content": "x"})
    changed = digest({"server": "prod", "path": "/tmp/a", "content": "y"})
    assert first == second
    assert first != changed


def test_correct_approval_is_consumed_once() -> None:
    registry = ApprovalRegistry()
    approved = write_digest()
    token = registry.issue_for_test("write_file", "principal", "prod", "/tmp/a", approved)
    assert registry.consume(token, "write_file", "principal", "prod", "/tmp/a", approved)
    assert not registry.consume(token, "write_file", "principal", "prod", "/tmp/a", approved)


def test_expired_approval_is_rejected() -> None:
    registry = ApprovalRegistry()
    approved = write_digest()
    token = registry.issue_for_test(
        "write_file", "principal", "prod", "/tmp/a", approved, ttl_seconds=0.001
    )
    time.sleep(0.01)
    assert not registry.consume(token, "write_file", "principal", "prod", "/tmp/a", approved)


def test_legacy_persisted_approval_without_arguments_digest_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "approvals.json"
    path.write_text(
        json.dumps(
            {
                "tokens": {
                    "x" * 32: {
                        "capability": "write_file",
                        "principal": "p",
                        "target": "prod",
                        "resource": "/tmp/a",
                        "expires_at": time.time() + 60,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)
    with pytest.raises(ValueError, match="invalid"):
        ApprovalRegistry.from_file(path)


def test_approval_file_requires_private_permissions(tmp_path: Path) -> None:
    path = tmp_path / "approvals.json"
    approved = write_digest()
    path.write_text(
        json.dumps(
            {
                "tokens": {
                    "x" * 32: {
                        "capability": "write_file",
                        "principal": "p",
                        "target": "prod",
                        "resource": "/tmp/a",
                        "arguments_digest": approved,
                        "expires_at": time.time() + 60,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o644)
    with pytest.raises(ValueError, match="permissions"):
        ApprovalRegistry.from_file(path)
    path.chmod(0o600)
    registry = ApprovalRegistry.from_file(path)
    assert registry.consume("x" * 32, "write_file", "p", "prod", "/tmp/a", approved)
    assert json.loads(path.read_text(encoding="utf-8")) == {"tokens": {}}
    restarted = ApprovalRegistry.from_file(path)
    assert not restarted.consume("x" * 32, "write_file", "p", "prod", "/tmp/a", approved)


def test_atomic_operator_replacement_is_reloaded_without_restart(tmp_path: Path) -> None:
    path = tmp_path / "approvals.json"
    path.write_text('{"tokens": {}}\n', encoding="utf-8")
    path.chmod(0o600)
    registry = ApprovalRegistry.from_file(path)

    approved = write_digest()
    token = "y" * 32
    replacement = tmp_path / "approvals.next"
    replacement.write_text(
        json.dumps(
            {
                "tokens": {
                    token: {
                        "capability": "write_file",
                        "principal": "operator",
                        "target": "prod",
                        "resource": "/tmp/a",
                        "arguments_digest": approved,
                        "expires_at": time.time() + 60,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    replacement.chmod(0o600)
    replacement.replace(path)

    assert registry.reload() is True
    assert registry.has_matching("write_file", "operator", "prod", "/tmp/a", approved)
    assert registry.consume_matching("write_file", "operator", "prod", "/tmp/a", approved)
    assert json.loads(path.read_text(encoding="utf-8")) == {"tokens": {}}


def test_matching_lookup_does_not_consume_record() -> None:
    registry = ApprovalRegistry()
    approved = write_digest()
    registry.issue_for_test("write_file", "operator", "prod", "/tmp/a", approved)
    assert registry.has_matching("write_file", "operator", "prod", "/tmp/a", approved)
    assert registry.has_matching("write_file", "operator", "prod", "/tmp/a", approved)
    assert registry.consume_matching("write_file", "operator", "prod", "/tmp/a", approved)
    assert not registry.has_matching("write_file", "operator", "prod", "/tmp/a", approved)


def test_operator_cli_issues_reloadable_argument_bound_approval(tmp_path: Path) -> None:
    path = tmp_path / "approvals.json"
    root = Path(__file__).resolve().parents[2]
    env = dict(os.environ)
    env["MCP_SERVERS"] = json.dumps(
        {
            "prod": {
                "type": "mikrus",
                "key": "test-key",
                "srv": "srv-id",
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
    approved = write_digest()
    assert issued["arguments_digest"] == approved
    assert issued["target_identity"] == "mikrus:srv-id"
    assert "approval_id" not in issued
    assert path.stat().st_mode & 0o077 == 0
    registry = ApprovalRegistry.from_file(path)
    assert registry.consume_matching(
        "write_file", "operator", "mikrus:srv-id", "/tmp/a", approved
    )
