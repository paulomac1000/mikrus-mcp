from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from mikrus_mcp.kernel import ApprovalRegistry


def test_approval_is_bound_and_single_use() -> None:
    registry = ApprovalRegistry()
    token = registry.issue_for_test("write_file", "principal", "prod", "/tmp/a")
    assert not registry.consume(token, "write_file", "principal", "other", "/tmp/a")
    assert registry.consume(token, "write_file", "principal", "prod", "/tmp/a")


def test_correct_approval_is_consumed_once() -> None:
    registry = ApprovalRegistry()
    token = registry.issue_for_test("write_file", "principal", "prod", "/tmp/a")
    assert registry.consume(token, "write_file", "principal", "prod", "/tmp/a")
    assert not registry.consume(token, "write_file", "principal", "prod", "/tmp/a")


def test_expired_approval_is_rejected() -> None:
    registry = ApprovalRegistry()
    token = registry.issue_for_test(
        "write_file", "principal", "prod", "/tmp/a", ttl_seconds=0.001
    )
    time.sleep(0.01)
    assert not registry.consume(token, "write_file", "principal", "prod", "/tmp/a")


def test_approval_file_requires_private_permissions(tmp_path: Path) -> None:
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
    path.chmod(0o644)
    with pytest.raises(ValueError, match="permissions"):
        ApprovalRegistry.from_file(path)
    path.chmod(0o600)
    registry = ApprovalRegistry.from_file(path)
    assert registry.consume("x" * 32, "write_file", "p", "prod", "/tmp/a")
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted == {"tokens": {}}
    restarted = ApprovalRegistry.from_file(path)
    assert not restarted.consume("x" * 32, "write_file", "p", "prod", "/tmp/a")


def test_atomic_operator_replacement_is_reloaded_without_restart(tmp_path: Path) -> None:
    path = tmp_path / "approvals.json"
    path.write_text('{"tokens": {}}\n', encoding="utf-8")
    path.chmod(0o600)
    registry = ApprovalRegistry.from_file(path)

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
    assert registry.has_matching("write_file", "operator", "prod", "/tmp/a")
    assert registry.consume_matching("write_file", "operator", "prod", "/tmp/a")
    assert json.loads(path.read_text(encoding="utf-8")) == {"tokens": {}}


def test_matching_lookup_does_not_consume_record() -> None:
    registry = ApprovalRegistry()
    registry.issue_for_test("write_file", "operator", "prod", "/tmp/a")
    assert registry.has_matching("write_file", "operator", "prod", "/tmp/a")
    assert registry.has_matching("write_file", "operator", "prod", "/tmp/a")
    assert registry.consume_matching("write_file", "operator", "prod", "/tmp/a")
    assert not registry.has_matching("write_file", "operator", "prod", "/tmp/a")


def test_operator_cli_issues_reloadable_approval(tmp_path: Path) -> None:
    import subprocess
    import sys

    path = tmp_path / "approvals.json"
    root = Path(__file__).resolve().parents[2]
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
            "--target",
            "prod",
            "--resource",
            "/tmp/a",
            "--ttl-seconds",
            "60",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    issued = json.loads(completed.stdout)
    assert "approval_id" not in issued
    assert path.stat().st_mode & 0o077 == 0
    registry = ApprovalRegistry.from_file(path)
    assert registry.consume_matching("write_file", "operator", "prod", "/tmp/a")
