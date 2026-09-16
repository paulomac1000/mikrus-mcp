"""Acceptance coverage for durable remote jobs (issue #19).

Exercises the SSH-side job helper as a local subprocess, the durable
JSON store, and the coordinating registry: durable ID issuance before
completion, retry idempotency, PID-reuse protection, cursor paging,
wait bounds, cross-instance durability, and the synthetic-time state
machine. No network and no real SSH.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mikrus_mcp.clients import ssh as ssh_module
from mikrus_mcp.errors import AppError, ErrorCode
from mikrus_mcp.remote_jobs import (
    DurableRemoteJobRegistry,
    RemoteJobRecord,
    RemoteJobStore,
    request_digest,
)


def _job_root(home: Path) -> Path:
    return home / ".cache" / "mikrus-mcp" / "remote-jobs"


def _run_helper(
    home: Path, payload: dict[str, object], *, timeout: float = 30.0
) -> dict[str, object]:
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
    return json.loads(completed.stdout.decode())


def _kill_group(record: dict[str, object]) -> None:
    identity = record.get("runtimeIdentity")
    if not isinstance(identity, dict):
        return
    pgid = identity.get("pgid")
    if pgid is None:
        return
    try:
        os.killpg(int(pgid), signal.SIGKILL)
    except (OSError, ValueError):
        pass


def test_remote_job_helper_issues_durable_id_and_retry_has_no_duplicate(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    job_id = "d" * 32
    start_payload: dict[str, object] = {
        "operation": "start",
        "job_id": job_id,
        "request_digest": "1" * 64,
        "executable": sys.executable,
        "argv": ["-c", "import time; time.sleep(60)"],
        "worker": ssh_module._REMOTE_JOB_WORKER,
    }
    record = _run_helper(home, start_payload)
    job_dir = _job_root(home) / job_id
    try:
        assert record["state"] in {"queued", "running"}
        assert (job_dir / "record.json").is_file()

        identity: dict[str, object] = {}
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            stored = json.loads((job_dir / "record.json").read_text())
            candidate = stored.get("runtimeIdentity")
            if isinstance(candidate, dict) and candidate.get("pid"):
                identity = candidate
                break
            time.sleep(0.1)
        assert identity.get("pid") and identity.get("pgid") and identity.get("startTicks")

        again = _run_helper(home, start_payload)
        assert again["jobId"] == job_id
        assert again["state"] in {"queued", "running"}
        assert again.get("runtimeIdentity") == identity
        assert [entry.name for entry in _job_root(home).iterdir()] == [job_id]

        cancelled = _run_helper(home, {"operation": "cancel", "job_id": job_id, "reason": "test"})
        assert cancelled["state"] == "cancelled"
        assert cancelled["terminated"] is True
    finally:
        if (job_dir / "record.json").exists():
            _kill_group(json.loads((job_dir / "record.json").read_text()))


def test_remote_job_helper_cancel_rejects_reused_pid_identity(tmp_path: Path) -> None:
    child = subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    home = tmp_path / "home"
    job_id = "r" * 32
    job_dir = _job_root(home) / job_id
    job_dir.mkdir(parents=True)
    try:
        stat_fields = Path(f"/proc/{child.pid}/stat").read_text("ascii").split()
        record = {
            "jobId": job_id,
            "state": "running",
            "runtimeIdentity": {
                "pid": str(child.pid),
                "pgid": str(os.getpgid(child.pid)),
                "startTicks": str(int(stat_fields[21]) + 1),
            },
        }
        (job_dir / "record.json").write_text(json.dumps(record))

        payload = _run_helper(home, {"operation": "cancel", "job_id": job_id, "reason": "test"})
        assert payload["error"] == "CONFLICT"
        assert child.poll() is None
        assert json.loads((job_dir / "record.json").read_text())["state"] == "running"
    finally:
        try:
            os.killpg(os.getpgid(child.pid), signal.SIGKILL)
        except (OSError, ValueError):
            pass
        child.wait(timeout=5)


def test_remote_job_helper_start_idempotency_conflict(tmp_path: Path) -> None:
    home = tmp_path / "home"
    job_id = "c" * 32
    job_dir = _job_root(home) / job_id
    job_dir.mkdir(parents=True)
    seeded = {"jobId": job_id, "state": "queued", "requestDigest": "a" * 64}
    (job_dir / "record.json").write_text(json.dumps(seeded))
    payload_base: dict[str, object] = {
        "operation": "start",
        "job_id": job_id,
        "executable": sys.executable,
        "argv": ["-c", "import time; time.sleep(60)"],
        "worker": ssh_module._REMOTE_JOB_WORKER,
    }

    conflict = _run_helper(home, {**payload_base, "request_digest": "b" * 64})
    assert conflict["error"] == "IDEMPOTENCY_CONFLICT"
    assert (job_dir / "record.json").read_text() == json.dumps(seeded)

    matched = _run_helper(home, {**payload_base, "request_digest": "a" * 64})
    assert matched["jobId"] == job_id
    assert matched["state"] == "queued"
    stored = json.loads((job_dir / "record.json").read_text())
    assert stored["state"] == "queued"
    assert "runtimeIdentity" not in stored


def test_remote_job_helper_output_cursor_paging(tmp_path: Path) -> None:
    home = tmp_path / "home"
    job_id = "o" * 32
    job_dir = _job_root(home) / job_id
    job_dir.mkdir(parents=True)
    body = "a" * 700 + "b" * 700 + "END"
    (job_dir / "stdout").write_text(body)
    (job_dir / "record.json").write_text(json.dumps({"jobId": job_id, "state": "running"}))

    collected: list[str] = []
    offset = 0
    pages = 0
    eof = False
    while not eof:
        page = _run_helper(
            home,
            {
                "operation": "output",
                "job_id": job_id,
                "stream": "stdout",
                "offset": offset,
                "max_bytes": 512,
            },
        )
        pages += 1
        assert len(page["data"]) <= 512
        assert page["next_offset"] == offset + len(page["data"])
        collected.append(str(page["data"]))
        offset = int(page["next_offset"])
        eof = bool(page["eof"])
        assert pages <= 5
    assert pages == 3
    assert "".join(collected) == body

    empty = _run_helper(
        home,
        {
            "operation": "output",
            "job_id": job_id,
            "stream": "stderr",
            "offset": 0,
            "max_bytes": 512,
        },
    )
    assert empty["data"] == ""
    assert empty["eof"] is True


def test_remote_job_helper_wait_is_bounded_and_terminal_returns_fast(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    running_id = "u" * 32
    running_dir = _job_root(home) / running_id
    running_dir.mkdir(parents=True)
    (running_dir / "record.json").write_text(json.dumps({"jobId": running_id, "state": "running"}))
    began = time.monotonic()
    payload = _run_helper(
        home, {"operation": "wait", "job_id": running_id, "timeout": 1}, timeout=15
    )
    elapsed = time.monotonic() - began
    assert payload["state"] == "running"
    assert 0.8 <= elapsed < 4.0

    done_id = "v" * 32
    done_dir = _job_root(home) / done_id
    done_dir.mkdir(parents=True)
    (done_dir / "record.json").write_text(json.dumps({"jobId": done_id, "state": "succeeded"}))
    began = time.monotonic()
    payload = _run_helper(home, {"operation": "wait", "job_id": done_id, "timeout": 5}, timeout=15)
    elapsed = time.monotonic() - began
    assert payload["state"] == "succeeded"
    assert elapsed < 1.0


def test_remote_jobs_survive_registry_restart(tmp_path: Path) -> None:
    store_path = tmp_path / "jobs.json"
    first = DurableRemoteJobRegistry(RemoteJobStore(store_path))
    now = datetime.now(UTC).isoformat()
    record, reused = first.create_or_reuse(
        principal="alice",
        server_id="srv1",
        target_identity="ssh:srv1:fingerprint",
        idempotency_key="build",
        request_digest_value=request_digest({"argv": ["build"]}),
        now=now,
    )
    assert reused is False
    first.update(
        job_id=record.job_id,
        principal="alice",
        state="running",
        now=datetime.now(UTC).isoformat(),
    )

    second = DurableRemoteJobRegistry(RemoteJobStore(store_path))
    revived = second.get(job_id=record.job_id, principal="alice")
    assert revived.state == "running"

    with pytest.raises(AppError) as exc:
        second.get(job_id=record.job_id, principal="bob")
    assert exc.value.code == ErrorCode.NOT_FOUND

    second.update(
        job_id=record.job_id,
        principal="alice",
        state="succeeded",
        now=datetime.now(UTC).isoformat(),
        exit_code=0,
    )
    assert first.get(job_id=record.job_id, principal="alice").state == "succeeded"


def test_remote_job_store_retry_dedup_and_conflict(tmp_path: Path) -> None:
    registry = DurableRemoteJobRegistry(RemoteJobStore(tmp_path / "jobs.json"))
    now = datetime.now(UTC).isoformat()
    first, created = registry.create_or_reuse(
        principal="alice",
        server_id="srv1",
        target_identity="ssh:srv1:fingerprint",
        idempotency_key="deploy",
        request_digest_value="a" * 64,
        now=now,
    )
    assert created is False
    second, reused = registry.create_or_reuse(
        principal="alice",
        server_id="srv1",
        target_identity="ssh:srv1:fingerprint",
        idempotency_key="deploy",
        request_digest_value="a" * 64,
        now=now,
    )
    assert reused is True
    assert second.job_id == first.job_id
    assert len(registry.store.load()) == 1

    with pytest.raises(AppError) as exc:
        registry.create_or_reuse(
            principal="alice",
            server_id="srv1",
            target_identity="ssh:srv1:fingerprint",
            idempotency_key="deploy",
            request_digest_value="b" * 64,
            now=now,
        )
    assert exc.value.code == ErrorCode.CONFLICT
    assert len(registry.store.load()) == 1


def test_remote_job_cursor_offsets_survive_round_trip() -> None:
    record = RemoteJobRecord.create(
        principal="alice",
        server_id="srv1",
        target_identity="ssh:srv1:fingerprint",
        idempotency_key="cursor-check",
        request_digest_value="a" * 64,
        now="2026-09-15T00:00:00Z",
    )
    record.stdout_offset = 123
    record.stderr_offset = 7

    restored = RemoteJobRecord.from_dict(record.as_dict())
    assert restored.stdout_offset == 123
    assert restored.stderr_offset == 7


def test_remote_job_state_machine_with_synthetic_time(tmp_path: Path) -> None:
    registry = DurableRemoteJobRegistry(RemoteJobStore(tmp_path / "jobs.json"))
    record, _ = registry.create_or_reuse(
        principal="alice",
        server_id="srv1",
        target_identity="ssh:srv1:fingerprint",
        idempotency_key="state-machine",
        request_digest_value="a" * 64,
        now="2026-01-01T00:00:00+00:00",
    )
    running = registry.update(
        job_id=record.job_id,
        principal="alice",
        state="running",
        now="2026-01-01T01:00:00+00:00",
    )
    assert running.started_at == "2026-01-01T01:00:00+00:00"
    registry.update(
        job_id=record.job_id,
        principal="alice",
        state="succeeded",
        now="2026-01-01T02:00:00+00:00",
        exit_code=0,
    )
    assert [item.state for item in registry.store.load()] == ["succeeded"]

    with pytest.raises(ValueError):
        registry.update(
            job_id=record.job_id,
            principal="alice",
            state="queued",
            now="2026-01-01T03:00:00+00:00",
        )
    assert [item.state for item in registry.store.load()] == ["succeeded"]
