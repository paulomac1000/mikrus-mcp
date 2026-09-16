from __future__ import annotations

import json
import os
import subprocess  # noqa: S404
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from mikrus_mcp.clients import ssh as ssh_module

TEST_LIMIT_BYTES = 4096
VALID_JOB_ID = "j" * 32


def _home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    return home


def _job_root(home: Path) -> Path:
    return home / ".cache" / "mikrus-mcp" / "remote-jobs"


def _run_helper(payload: dict[str, Any], home: Path, timeout: int = 60) -> dict[str, Any]:
    environment = dict(os.environ)
    environment["HOME"] = str(home)
    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-c", ssh_module._REMOTE_JOB_HELPER],
        input=json.dumps(payload).encode(),
        capture_output=True,
        env=environment,
        timeout=timeout,
    )
    assert completed.returncode == 0, completed.stderr.decode()
    text = completed.stdout.decode().strip()
    return json.loads(text) if text else {}


def _start_job(home: Path, *, code: str, limit: int = TEST_LIMIT_BYTES) -> dict[str, Any]:
    return _run_helper(
        {
            "operation": "start",
            "job_id": VALID_JOB_ID,
            "request_digest": "d" * 64,
            "executable": sys.executable,
            "argv": ["-c", code],
            "output_limit_bytes": limit,
            "worker": ssh_module._REMOTE_JOB_WORKER,
        },
        home,
    )


def _run_to_terminal(home: Path, *, timeout: float = 30.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = _run_helper({"operation": "status", "job_id": VALID_JOB_ID}, home)
        if record.get("state") in {"succeeded", "failed", "cancelled", "lost", "expired"}:
            return record
        time.sleep(0.1)
    pytest.fail("remote job did not reach a terminal state")


def _read_record(home: Path) -> dict[str, Any]:
    record_path = _job_root(home) / VALID_JOB_ID / "record.json"
    return json.loads(record_path.read_text(encoding="utf-8"))


def test_noisy_output_is_capped_with_truncation_markers(tmp_path: Path) -> None:
    home = _home(tmp_path)
    _start_job(home, code="import sys\nsys.stdout.write('x' * (1024 * 1024))\n")
    record = _run_to_terminal(home)
    assert record["state"] == "succeeded"
    assert record["exitCode"] == 0
    assert record["stdoutTruncated"] is True
    assert record.get("outputCapped") is True
    assert record.get("stdoutDiscardedBytes", 0) > 0
    stdout_size = (_job_root(home) / VALID_JOB_ID / "stdout").stat().st_size
    assert stdout_size <= TEST_LIMIT_BYTES


def test_exact_boundary_output_succeeds_without_truncation(tmp_path: Path) -> None:
    home = _home(tmp_path)
    _start_job(home, code="import sys\nsys.stdout.write('x' * 4096)\n")
    record = _run_to_terminal(home)
    assert record["state"] == "succeeded"
    assert not record.get("stdoutTruncated")
    stdout_size = (_job_root(home) / VALID_JOB_ID / "stdout").stat().st_size
    assert stdout_size == TEST_LIMIT_BYTES


def test_stdout_and_stderr_bounds_are_independent(tmp_path: Path) -> None:
    home = _home(tmp_path)
    _start_job(
        home,
        code="import sys\nsys.stdout.write('o' * 8192)\nsys.stderr.write('e' * 1024)\n",
    )
    record = _run_to_terminal(home)
    assert record["state"] == "succeeded"
    assert record["stdoutTruncated"] is True
    assert record["stderrTruncated"] is False
    job_dir = _job_root(home) / VALID_JOB_ID
    assert (job_dir / "stdout").stat().st_size <= TEST_LIMIT_BYTES
    stderr_size = (job_dir / "stderr").stat().st_size
    assert stderr_size <= TEST_LIMIT_BYTES


def test_range_read_returns_bounded_slice_from_large_stream(tmp_path: Path) -> None:
    home = _home(tmp_path)
    job_dir = _job_root(home) / VALID_JOB_ID
    job_dir.mkdir(parents=True)
    payload = ("a" * 99 + "\n") * 52_000
    data = payload.encode()
    (job_dir / "stdout").write_bytes(data)
    (job_dir / "record.json").write_text(json.dumps({"jobId": VALID_JOB_ID, "state": "succeeded"}))
    first = _run_helper(
        {
            "operation": "output",
            "job_id": VALID_JOB_ID,
            "stream": "stdout",
            "offset": 0,
            "max_bytes": 65_536,
        },
        home,
    )
    assert first["next_offset"] == 65_536
    assert first["eof"] is False
    collected = first["data"].encode()
    offset = first["next_offset"]
    while True:
        chunk = _run_helper(
            {
                "operation": "output",
                "job_id": VALID_JOB_ID,
                "stream": "stdout",
                "offset": offset,
                "max_bytes": 65_536,
            },
            home,
        )
        collected += chunk["data"].encode()
        if chunk["eof"]:
            break
        offset = chunk["next_offset"]
    assert collected == data
    tail = _run_helper(
        {
            "operation": "output",
            "job_id": VALID_JOB_ID,
            "stream": "stdout",
            "offset": len(data) - 10,
            "max_bytes": 65_536,
        },
        home,
    )
    assert tail["data"].encode() == data[-10:]
    assert tail["eof"] is True


def test_helper_does_not_read_whole_stream_file_for_a_slice() -> None:
    assert "read_bytes" not in ssh_module._REMOTE_JOB_HELPER


def test_output_read_on_missing_stream_is_empty_eof(tmp_path: Path) -> None:
    home = _home(tmp_path)
    job_dir = _job_root(home) / VALID_JOB_ID
    job_dir.mkdir(parents=True)
    (job_dir / "record.json").write_text(json.dumps({"jobId": VALID_JOB_ID, "state": "running"}))
    result = _run_helper(
        {
            "operation": "output",
            "job_id": VALID_JOB_ID,
            "stream": "stderr",
            "offset": 0,
            "max_bytes": 16,
        },
        home,
    )
    assert result == {"data": "", "next_offset": 0, "eof": True}


def test_gc_removes_expired_terminal_job(tmp_path: Path) -> None:
    home = _home(tmp_path)
    job_dir = _job_root(home) / VALID_JOB_ID
    job_dir.mkdir(parents=True)
    (job_dir / "record.json").write_text(
        json.dumps(
            {
                "jobId": VALID_JOB_ID,
                "state": "succeeded",
                "finishedAt": time.time() - 10.0,
            }
        )
    )
    summary = _run_helper(
        {"operation": "gc", "retention_seconds": 5, "grace_seconds": 0, "max_entries": 256},
        home,
    )
    assert summary["removed"] == 1
    assert not job_dir.exists()


def test_gc_keeps_recent_terminal_job(tmp_path: Path) -> None:
    home = _home(tmp_path)
    job_dir = _job_root(home) / VALID_JOB_ID
    job_dir.mkdir(parents=True)
    (job_dir / "record.json").write_text(
        json.dumps(
            {
                "jobId": VALID_JOB_ID,
                "state": "succeeded",
                "finishedAt": time.time(),
            }
        )
    )
    summary = _run_helper(
        {"operation": "gc", "retention_seconds": 3600, "grace_seconds": 0, "max_entries": 256},
        home,
    )
    assert summary["removed"] == 0
    assert job_dir.exists()


def test_gc_never_removes_running_job_with_live_identity(tmp_path: Path) -> None:
    home = _home(tmp_path)
    job_dir = _job_root(home) / VALID_JOB_ID
    job_dir.mkdir(parents=True)
    child = subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(0.2)
        stat_fields = Path(f"/proc/{child.pid}/stat").read_text("ascii").split()
        (job_dir / "record.json").write_text(
            json.dumps(
                {
                    "jobId": VALID_JOB_ID,
                    "state": "running",
                    "runtimeIdentity": {
                        "pid": str(child.pid),
                        "pgid": str(child.pid),
                        "startTicks": stat_fields[21],
                    },
                }
            )
        )
        summary = _run_helper(
            {"operation": "gc", "retention_seconds": 0, "grace_seconds": 0, "max_entries": 256},
            home,
        )
        assert summary["removed"] == 0
        assert summary["keptActive"] == 1
        assert job_dir.exists()
    finally:
        child.kill()
        child.wait(timeout=5)


def test_gc_collects_running_job_with_dead_identity_after_grace(tmp_path: Path) -> None:
    home = _home(tmp_path)
    job_dir = _job_root(home) / VALID_JOB_ID
    job_dir.mkdir(parents=True)
    child = subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", "pass"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    child.wait(timeout=5)
    dead_pid = child.pid
    record = {
        "jobId": VALID_JOB_ID,
        "state": "running",
        "runtimeIdentity": {"pid": str(dead_pid), "pgid": str(dead_pid), "startTicks": "1"},
    }
    (job_dir / "record.json").write_text(json.dumps(record))
    old = time.time() - 7200
    os.utime(job_dir, (old, old))
    os.utime(job_dir / "record.json", (old, old))
    summary = _run_helper(
        {"operation": "gc", "retention_seconds": 604_800, "grace_seconds": 1, "max_entries": 256},
        home,
    )
    assert summary["removed"] == 1
    assert not job_dir.exists()


def test_gc_removal_is_idempotent_when_directory_already_absent(tmp_path: Path) -> None:
    home = _home(tmp_path)
    summary = _run_helper(
        {"operation": "gc", "retention_seconds": 1, "grace_seconds": 0, "max_entries": 256},
        home,
    )
    assert summary["removed"] == 0
    assert summary["errors"] == 0


def test_gc_removes_symlink_entry_without_escaping_managed_root(tmp_path: Path) -> None:
    home = _home(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "precious.txt").write_text("keep me")
    link = _job_root(home) / ("s" * 32)
    link.parent.mkdir(parents=True)
    link.symlink_to(outside, target_is_directory=True)
    old = time.time() - 7200
    os.utime(link, (old, old), follow_symlinks=False)
    summary = _run_helper(
        {"operation": "gc", "retention_seconds": 1, "grace_seconds": 0, "max_entries": 256},
        home,
    )
    assert summary["removed"] == 1
    assert not link.exists()
    assert (outside / "precious.txt").read_text() == "keep me"


def test_gc_collects_orphaned_start_directory_after_grace(tmp_path: Path) -> None:
    home = _home(tmp_path)
    orphan = _job_root(home) / ("o" * 32)
    orphan.mkdir(parents=True)
    old = time.time() - 7200
    os.utime(orphan, (old, old))
    fresh = _job_root(home) / ("f" * 32)
    fresh.mkdir(parents=True)
    summary = _run_helper(
        {
            "operation": "gc",
            "retention_seconds": 604_800,
            "grace_seconds": 3600,
            "max_entries": 256,
        },
        home,
    )
    assert summary["removed"] == 1
    assert not orphan.exists()
    assert fresh.exists()


def test_gc_is_restart_safe_across_fresh_helper_processes(tmp_path: Path) -> None:
    home = _home(tmp_path)
    for index in range(2):
        job_dir = _job_root(home) / (str(index) * 32)
        job_dir.mkdir(parents=True)
        (job_dir / "record.json").write_text(
            json.dumps(
                {
                    "jobId": str(index) * 32,
                    "state": "failed",
                    "finishedAt": time.time() - 10.0,
                }
            )
        )
        summary = _run_helper(
            {"operation": "gc", "retention_seconds": 5, "grace_seconds": 0, "max_entries": 256},
            home,
        )
        assert summary["removed"] == 1
        assert not job_dir.exists()


def test_gc_honors_bounded_scan_budget(tmp_path: Path) -> None:
    home = _home(tmp_path)
    for index in range(6):
        job_dir = _job_root(home) / (str(index) * 32)
        job_dir.mkdir(parents=True)
    summary = _run_helper(
        {"operation": "gc", "retention_seconds": 1, "grace_seconds": 0, "max_entries": 3},
        home,
    )
    assert summary["scanned"] == 3


# ---------------------------------------------------------------------------
# MCP-side integration: tombstones after payload cleanup, gc after start
# ---------------------------------------------------------------------------


def _ssh_target() -> Any:
    from mikrus_mcp.config import TargetConfig

    return TargetConfig("host", "ssh", host="server.example")


def _expired_record_client_kernel(tmp_path: Path, client: Any) -> tuple[Any, Any, Any]:
    from mikrus_mcp.approvals import ApprovalRegistry
    from mikrus_mcp.config import Settings
    from mikrus_mcp.kernel import CallerContext, InvocationKernel
    from mikrus_mcp.remote_jobs import RemoteJobRecord, RemoteJobStore
    from mikrus_mcp.targets import TargetRegistry

    settings = Settings(
        targets={"host": _ssh_target()},
        default_target="host",
        allowed_scopes=frozenset(
            {"tool:*", "target:*", "target-id:*", "resource:*", "data:*", "write:server"}
        ),
        write_enabled=True,
        remote_job_store_file=tmp_path / "jobs.json",
    )
    store = RemoteJobStore(tmp_path / "jobs.json")
    record = RemoteJobRecord.create(
        principal="principal",
        server_id="host",
        target_identity=client.stable_identity,
        idempotency_key="tombstone",
        request_digest_value="a" * 64,
        now="2026-09-10T12:00:00Z",
    )
    record.transition("succeeded", now="2026-09-10T12:05:00Z")
    store.save(record)
    kernel = InvocationKernel(
        settings,
        registry=TargetRegistry(
            dict(settings.targets),
            factory=lambda _: client,  # type: ignore[arg-type]
        ),
        approvals=ApprovalRegistry(),
    )
    caller = CallerContext("principal", settings.allowed_scopes)
    return kernel, caller, record


@pytest.mark.asyncio
async def test_status_returns_expired_tombstone_after_remote_payload_removal(
    tmp_path: Path,
) -> None:
    from mikrus_mcp.errors import AppError, ErrorCode

    class GoneStatusClient:
        def __init__(self, config: Any) -> None:
            self.config = config
            self.stable_identity = f"{config.stable_identity}#host-key=SHA256:dk"

        async def open(self) -> None:
            return None

        async def close(self) -> None:
            return None

        async def remote_job_status(self, *, job_id: str) -> dict[str, object]:
            raise AppError(ErrorCode.NOT_FOUND, "remote job not found")

    kernel, caller, record = _expired_record_client_kernel(
        tmp_path, GoneStatusClient(_ssh_target())
    )
    result = await kernel.invoke("remote_job_status", {"job_id": record.job_id}, caller)
    assert result["success"] is True
    assert result["data"]["state"] == "succeeded"
    assert result["data"]["remotePayloadRemoved"] is True


@pytest.mark.asyncio
async def test_result_returns_expired_tombstone_after_remote_payload_removal(
    tmp_path: Path,
) -> None:
    from mikrus_mcp.errors import AppError, ErrorCode

    class GoneResultClient:
        def __init__(self, config: Any) -> None:
            self.config = config
            self.stable_identity = f"{config.stable_identity}#host-key=SHA256:dk"

        async def open(self) -> None:
            return None

        async def close(self) -> None:
            return None

        async def remote_job_result(self, *, job_id: str) -> dict[str, object]:
            raise AppError(ErrorCode.NOT_FOUND, "remote job not found")

    kernel, caller, record = _expired_record_client_kernel(
        tmp_path, GoneResultClient(_ssh_target())
    )
    result = await kernel.invoke("remote_job_result", {"job_id": record.job_id}, caller)
    assert result["success"] is True
    assert result["data"]["state"] == "succeeded"
    assert result["data"]["remotePayloadRemoved"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_gc", [False, True])
async def test_start_reports_gc_summary_and_typed_gc_failure(tmp_path: Path, fail_gc: bool) -> None:
    from mikrus_mcp.approvals import ApprovalRegistry, normalized_arguments_digest
    from mikrus_mcp.config import Settings
    from mikrus_mcp.errors import AppError, ErrorCode
    from mikrus_mcp.kernel import CallerContext, InvocationKernel
    from mikrus_mcp.targets import TargetRegistry

    class GcStartClient:
        def __init__(self, config: Any) -> None:
            self.config = config
            self.stable_identity = f"{config.stable_identity}#host-key=SHA256:dk"

        async def open(self) -> None:
            return None

        async def close(self) -> None:
            return None

        async def remote_job_start(self, **_: object) -> dict[str, object]:
            return {"jobId": "started", "state": "queued"}

        async def remote_job_gc(self, **_: object) -> dict[str, object]:
            if fail_gc:
                raise AppError(ErrorCode.UNAVAILABLE, "gc helper failed")
            return {"scanned": 3, "removed": 1, "keptActive": 0, "keptRecent": 2, "errors": 0}

    client = GcStartClient(_ssh_target())
    settings = Settings(
        targets={"host": _ssh_target()},
        default_target="host",
        allowed_scopes=frozenset(
            {"tool:*", "target:*", "target-id:*", "resource:*", "data:*", "write:server"}
        ),
        write_enabled=True,
        remote_job_store_file=tmp_path / "jobs.json",
    )
    approvals = ApprovalRegistry()
    kernel = InvocationKernel(
        settings,
        registry=TargetRegistry(
            dict(settings.targets),
            factory=lambda _: client,  # type: ignore[arg-type]
        ),
        approvals=approvals,
    )
    caller = CallerContext("principal", settings.allowed_scopes)
    arguments = {
        "idempotency_key": "gc-check",
        "executable": "tail",
        "argv": ["-f", "/tmp/x"],
    }
    approvals.issue_for_test(
        "remote_job_start",
        "principal",
        client.stable_identity,
        "gc-check",
        normalized_arguments_digest(arguments),
    )
    result = await kernel.invoke("remote_job_start", arguments, caller)
    assert result["success"] is True
    if fail_gc:
        assert result["data"]["gc"] == {"gcError": "UNAVAILABLE", "gcMessage": "gc helper failed"}
    else:
        assert result["data"]["gc"] == {
            "scanned": 3,
            "removed": 1,
            "keptActive": 0,
            "keptRecent": 2,
            "errors": 0,
        }


def test_worker_closes_stdin_so_eof_readers_terminate(tmp_path: Path) -> None:
    home = _home(tmp_path)
    _start_job(home, code="import sys\nsys.stdin.read()\nprint('done')\n")
    record = _run_to_terminal(home, timeout=20.0)
    assert record["state"] == "succeeded"


def test_gc_legacy_terminal_record_without_finished_at_uses_mtime(tmp_path: Path) -> None:
    home = _home(tmp_path)
    job_dir = _job_root(home) / VALID_JOB_ID
    job_dir.mkdir(parents=True)
    record_path = job_dir / "record.json"
    record_path.write_text(json.dumps({"jobId": VALID_JOB_ID, "state": "succeeded"}))
    old = time.time() - 10.0
    os.utime(record_path, (old, old))
    summary = _run_helper(
        {"operation": "gc", "retention_seconds": 5, "grace_seconds": 0, "max_entries": 256},
        home,
    )
    assert summary["removed"] == 1

    recent_job = _job_root(home) / ("r" * 32)
    recent_job.mkdir(parents=True)
    recent_record = recent_job / "record.json"
    recent_record.write_text(json.dumps({"jobId": "r" * 32, "state": "succeeded"}))
    summary = _run_helper(
        {"operation": "gc", "retention_seconds": 5, "grace_seconds": 0, "max_entries": 256},
        home,
    )
    assert summary["removed"] == 0
    assert recent_job.exists()


def test_gc_collects_stale_queued_record_without_identity(tmp_path: Path) -> None:
    home = _home(tmp_path)
    job_dir = _job_root(home) / VALID_JOB_ID
    job_dir.mkdir(parents=True)
    record_path = job_dir / "record.json"
    record_path.write_text(json.dumps({"jobId": VALID_JOB_ID, "state": "queued"}))
    old = time.time() - 7200.0
    os.utime(record_path, (old, old))
    os.utime(job_dir, (old, old))
    summary = _run_helper(
        {"operation": "gc", "retention_seconds": 604_800, "grace_seconds": 1, "max_entries": 256},
        home,
    )
    assert summary["removed"] == 1
    assert not job_dir.exists()


def test_gc_keeps_fresh_queued_record_without_identity(tmp_path: Path) -> None:
    home = _home(tmp_path)
    job_dir = _job_root(home) / VALID_JOB_ID
    job_dir.mkdir(parents=True)
    (job_dir / "record.json").write_text(json.dumps({"jobId": VALID_JOB_ID, "state": "queued"}))
    summary = _run_helper(
        {
            "operation": "gc",
            "retention_seconds": 604_800,
            "grace_seconds": 3600,
            "max_entries": 256,
        },
        home,
    )
    assert summary["removed"] == 0
    assert summary["keptRecent"] == 1
    assert job_dir.exists()


def test_child_own_file_writes_are_not_capped_by_output_policy(tmp_path: Path) -> None:
    """Regression: output policy caps only stored streams, not child's own files."""
    home = _home(tmp_path)
    child_code = (
        "import sys, tempfile, os\n"
        "with tempfile.NamedTemporaryFile(delete=False) as f:\n"
        "    f.write(b'z' * (64 * 1024))\n"
        "    own = f.name\n"
        "sys.stdout.write('ok')\n"
        "print(own)\n"
    )
    _start_job(home, code=child_code)
    record = _run_to_terminal(home)
    assert record["state"] == "succeeded"
    assert not record.get("outputCapped")


def test_gc_rotating_cursor_eventually_reaches_entries_beyond_budget(tmp_path: Path) -> None:
    home = _home(tmp_path)
    stale_names = [f"{index:032d}" for index in range(10)]
    old = time.time() - 7200.0
    for name in stale_names:
        job_dir = _job_root(home) / name
        job_dir.mkdir(parents=True)
        record_path = job_dir / "record.json"
        record_path.write_text(
            json.dumps({"jobId": name, "state": "succeeded", "finishedAt": old - 10.0})
        )
        os.utime(record_path, (old, old))
        os.utime(job_dir, (old, old))
    gc_args = {"operation": "gc", "retention_seconds": 5, "grace_seconds": 0, "max_entries": 4}
    removed_total = 0
    for _ in range(6):
        summary = _run_helper(gc_args, home)
        removed_total += summary["removed"]
        if removed_total == len(stale_names):
            break
    assert removed_total == len(stale_names)
    remaining = [name for name in stale_names if (_job_root(home) / name).exists()]
    assert remaining == []
