from __future__ import annotations

import hashlib
import json
import os
import shutil
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


def _bucket_of(name: str) -> int:
    return int.from_bytes(hashlib.sha256(name.encode() + b"/bucket").digest()[:8], "big") % 65536


def _job_dir(home: Path, name: str) -> Path:
    bucket = _bucket_of(name)
    return (
        _job_root(home)
        / f"s{_shard_of(name):x}"
        / f"b{bucket >> 8:x}"
        / f"c{bucket & 0xFF:x}"
        / name
    )


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


def _start_job(
    home: Path,
    *,
    code: str,
    limit: int = TEST_LIMIT_BYTES,
    payload_stdin: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "operation": "start",
        "job_id": VALID_JOB_ID,
        "request_digest": "d" * 64,
        "executable": sys.executable,
        "argv": ["-c", code],
        "output_limit_bytes": limit,
        "drain_grace_seconds": 3.0,
        "worker": ssh_module._REMOTE_JOB_WORKER,
    }
    if payload_stdin is not None:
        payload["stdin"] = payload_stdin
    return _run_helper(payload, home)


def _shard_of(name: str, shards: int = 16) -> int:
    import hashlib

    return int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], "big") % shards


def _run_to_terminal(home: Path, *, timeout: float = 30.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = _run_helper({"operation": "status", "job_id": VALID_JOB_ID}, home)
        if record.get("state") in {"succeeded", "failed", "cancelled", "lost", "expired"}:
            return record
        time.sleep(0.1)
    pytest.fail("remote job did not reach a terminal state")


def _read_record(home: Path) -> dict[str, Any]:
    record_path = _job_dir(home, VALID_JOB_ID) / "record.json"
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
    stdout_size = (_job_dir(home, VALID_JOB_ID) / "stdout").stat().st_size
    assert stdout_size <= TEST_LIMIT_BYTES


def test_exact_boundary_output_succeeds_without_truncation(tmp_path: Path) -> None:
    home = _home(tmp_path)
    _start_job(home, code="import sys\nsys.stdout.write('x' * 4096)\n")
    record = _run_to_terminal(home)
    assert record["state"] == "succeeded"
    assert not record.get("stdoutTruncated")
    stdout_size = (_job_dir(home, VALID_JOB_ID) / "stdout").stat().st_size
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
    job_dir = _job_dir(home, VALID_JOB_ID)
    assert (job_dir / "stdout").stat().st_size <= TEST_LIMIT_BYTES
    stderr_size = (job_dir / "stderr").stat().st_size
    assert stderr_size <= TEST_LIMIT_BYTES


def test_range_read_returns_bounded_slice_from_large_stream(tmp_path: Path) -> None:
    home = _home(tmp_path)
    job_dir = _job_dir(home, VALID_JOB_ID)
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
    job_dir = _job_dir(home, VALID_JOB_ID)
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
    job_dir = _job_dir(home, VALID_JOB_ID)
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
        {
            "operation": "gc",
            "retention_seconds": 5,
            "grace_seconds": 0,
            "max_entries": 256,
            "shard": _shard_of(VALID_JOB_ID),
        },
        home,
    )
    assert summary["removed"] == 1
    assert not job_dir.exists()


def test_gc_keeps_recent_terminal_job(tmp_path: Path) -> None:
    home = _home(tmp_path)
    job_dir = _job_dir(home, VALID_JOB_ID)
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
        {
            "operation": "gc",
            "retention_seconds": 3600,
            "grace_seconds": 0,
            "max_entries": 256,
            "shard": _shard_of(VALID_JOB_ID),
        },
        home,
    )
    assert summary["removed"] == 0
    assert job_dir.exists()


def test_gc_never_removes_running_job_with_live_identity(tmp_path: Path) -> None:
    home = _home(tmp_path)
    job_dir = _job_dir(home, VALID_JOB_ID)
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
            {
                "operation": "gc",
                "retention_seconds": 0,
                "grace_seconds": 0,
                "max_entries": 256,
                "shard": _shard_of(VALID_JOB_ID),
            },
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
    job_dir = _job_dir(home, VALID_JOB_ID)
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
        {
            "operation": "gc",
            "retention_seconds": 604_800,
            "grace_seconds": 1,
            "max_entries": 256,
            "shard": _shard_of(VALID_JOB_ID),
        },
        home,
    )
    assert summary["removed"] == 1
    assert not job_dir.exists()


def test_gc_removal_is_idempotent_when_directory_already_absent(tmp_path: Path) -> None:
    home = _home(tmp_path)
    summary = _run_helper(
        {
            "operation": "gc",
            "retention_seconds": 1,
            "grace_seconds": 0,
            "max_entries": 256,
            "shard": _shard_of(VALID_JOB_ID),
        },
        home,
    )
    assert summary["removed"] == 0
    assert summary["errors"] == 0


def test_gc_removes_symlink_entry_without_escaping_managed_root(tmp_path: Path) -> None:
    home = _home(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "precious.txt").write_text("keep me")
    link = _job_dir(home, ("s" * 32))
    link.parent.mkdir(parents=True)
    link.symlink_to(outside, target_is_directory=True)
    old = time.time() - 7200
    os.utime(link, (old, old), follow_symlinks=False)
    summary = _run_helper(
        {
            "operation": "gc",
            "retention_seconds": 1,
            "grace_seconds": 0,
            "max_entries": 256,
            "shard": _shard_of("s" * 32),
        },
        home,
    )
    assert summary["removed"] == 1
    assert not link.exists()
    assert (outside / "precious.txt").read_text() == "keep me"


def test_gc_collects_orphaned_start_directory_after_grace(tmp_path: Path) -> None:
    home = _home(tmp_path)
    orphan = _job_dir(home, ("o" * 32))
    orphan.mkdir(parents=True)
    old = time.time() - 7200
    os.utime(orphan, (old, old))
    fresh = _job_dir(home, ("f" * 32))
    fresh.mkdir(parents=True)
    summary = _run_helper(
        {
            "operation": "gc",
            "retention_seconds": 604_800,
            "grace_seconds": 3600,
            "max_entries": 256,
            "shard": _shard_of("o" * 32),
        },
        home,
    )
    assert summary["removed"] == 1
    assert not orphan.exists()
    assert fresh.exists()


def test_gc_is_restart_safe_across_fresh_helper_processes(tmp_path: Path) -> None:
    home = _home(tmp_path)
    for index in range(2):
        job_dir = _job_dir(home, (str(index) * 32))
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
            {
                "operation": "gc",
                "retention_seconds": 5,
                "grace_seconds": 0,
                "max_entries": 256,
                "shard": _shard_of(str(index) * 32),
            },
            home,
        )
        assert summary["removed"] == 1
        assert not job_dir.exists()


def test_gc_honors_bounded_scan_budget(tmp_path: Path) -> None:
    home = _home(tmp_path)
    old = time.time() - 7200.0
    for index in range(6):
        job_dir = _job_dir(home, (str(index) * 32))
        job_dir.mkdir(parents=True)
        record_path = job_dir / "record.json"
        record_path.write_text(
            json.dumps({"jobId": str(index) * 32, "state": "succeeded", "finishedAt": old - 5.0})
        )
        os.utime(record_path, (old, old))
        os.utime(job_dir, (old, old))
    total_scanned = 0
    for shard in range(16):
        summary = _run_helper(
            {
                "operation": "gc",
                "retention_seconds": 1,
                "grace_seconds": 0,
                "max_entries": 3,
                "shards": 16,
                "shard": shard,
            },
            home,
        )
        assert summary["scanned"] <= 3
        total_scanned += summary["scanned"]
    assert total_scanned == 6


def test_gc_legacy_terminal_record_without_finished_at_uses_mtime(tmp_path: Path) -> None:
    home = _home(tmp_path)
    job_dir = _job_dir(home, VALID_JOB_ID)
    job_dir.mkdir(parents=True)
    record_path = job_dir / "record.json"
    record_path.write_text(json.dumps({"jobId": VALID_JOB_ID, "state": "succeeded"}))
    old = time.time() - 10.0
    os.utime(record_path, (old, old))
    summary = _run_helper(
        {
            "operation": "gc",
            "retention_seconds": 5,
            "grace_seconds": 0,
            "max_entries": 256,
            "shard": _shard_of(VALID_JOB_ID),
        },
        home,
    )
    assert summary["removed"] == 1

    recent_job = _job_dir(home, ("r" * 32))
    recent_job.mkdir(parents=True)
    recent_record = recent_job / "record.json"
    recent_record.write_text(json.dumps({"jobId": "r" * 32, "state": "succeeded"}))
    summary = _run_helper(
        {
            "operation": "gc",
            "retention_seconds": 5,
            "grace_seconds": 0,
            "max_entries": 256,
            "shard": _shard_of("r" * 32),
        },
        home,
    )
    assert summary["removed"] == 0
    assert recent_job.exists()


def test_gc_collects_stale_queued_record_without_identity(tmp_path: Path) -> None:
    home = _home(tmp_path)
    job_dir = _job_dir(home, VALID_JOB_ID)
    job_dir.mkdir(parents=True)
    record_path = job_dir / "record.json"
    record_path.write_text(json.dumps({"jobId": VALID_JOB_ID, "state": "queued"}))
    old = time.time() - 7200.0
    os.utime(record_path, (old, old))
    os.utime(job_dir, (old, old))
    summary = _run_helper(
        {
            "operation": "gc",
            "retention_seconds": 604_800,
            "grace_seconds": 1,
            "max_entries": 256,
            "shard": _shard_of(VALID_JOB_ID),
        },
        home,
    )
    assert summary["removed"] == 1
    assert not job_dir.exists()


def test_gc_keeps_fresh_queued_record_without_identity(tmp_path: Path) -> None:
    home = _home(tmp_path)
    job_dir = _job_dir(home, VALID_JOB_ID)
    job_dir.mkdir(parents=True)
    (job_dir / "record.json").write_text(json.dumps({"jobId": VALID_JOB_ID, "state": "queued"}))
    summary = _run_helper(
        {
            "operation": "gc",
            "retention_seconds": 604_800,
            "grace_seconds": 3600,
            "max_entries": 256,
            "shard": _shard_of(VALID_JOB_ID),
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


def test_gc_rotating_shards_eventually_reach_every_entry(tmp_path: Path) -> None:
    home = _home(tmp_path)
    total = 64
    stale_names = [f"{index:032d}" for index in range(total)]
    old = time.time() - 7200.0
    for name in stale_names:
        job_dir = _job_dir(home, name)
        job_dir.mkdir(parents=True)
        record_path = job_dir / "record.json"
        record_path.write_text(
            json.dumps({"jobId": name, "state": "succeeded", "finishedAt": old - 10.0})
        )
        os.utime(record_path, (old, old))
        os.utime(job_dir, (old, old))
    removed_total = 0
    enumerated = []
    for shard in range(16):
        summary = _run_helper(
            {
                "operation": "gc",
                "retention_seconds": 5,
                "grace_seconds": 0,
                "max_entries": 64,
                "shards": 16,
                "shard": shard,
            },
            home,
        )
        removed_total += summary["removed"]
        enumerated.append(summary["enumerated"])
        if removed_total == total:
            break
    assert removed_total == total
    remaining = [name for name in stale_names if _job_dir(home, name).exists()]
    assert remaining == []


def test_gc_visit_budget_bounds_enumeration_with_thousands_of_entries(
    tmp_path: Path,
) -> None:
    """Supervisor round-9 regression: the enumerator reports the ACTUAL number
    of root entries visited, and with max_entries=3 it must visit only the
    small bounded multiple of that budget even when thousands of job dirs
    exist — never the whole root."""
    home = _home(tmp_path)

    def shard_of(name: str) -> int:
        return int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], "big") % 16

    names: list[str] = []
    index = 0
    while len(names) < 2000:
        candidate = f"{index:032d}"
        index += 1
        if shard_of(candidate) == 0:
            names.append(candidate)
    old = time.time() - 7200.0
    for name in names:
        job_dir = _job_dir(home, name)
        job_dir.mkdir(parents=True)
        record_path = job_dir / "record.json"
        record_path.write_text(
            json.dumps({"jobId": name, "state": "succeeded", "finishedAt": old - 5.0})
        )
        os.utime(record_path, (old, old))
        os.utime(job_dir, (old, old))
    summary = _run_helper(
        {
            "operation": "gc",
            "retention_seconds": 5,
            "grace_seconds": 3600,
            "max_entries": 3,
            "shards": 16,
            "shard": 0,
        },
        home,
    )
    # Every entry lives in shard 0 and is stale, so every visited entry
    # qualifies: visited == enum_budget == enumerated.
    assert summary["visited"] == 64
    assert summary["visited"] < len(names)
    assert summary["enumerated"] == summary["visited"]
    assert summary["removed"] == 3
    assert summary["scanned"] == 3
    assert summary["errors"] == 0

    second = _run_helper(
        {
            "operation": "gc",
            "retention_seconds": 5,
            "grace_seconds": 0,
            "max_entries": 3,
            "shards": 16,
            "shard": 0,
        },
        home,
    )
    assert second["visited"] == 64
    assert second["removed"] == 3
    assert summary["removed"] + second["removed"] == 6


def test_same_group_descendant_is_terminated_on_drain_timeout(tmp_path: Path) -> None:
    home = _home(tmp_path)
    child_code = (
        "import subprocess, sys\n"
        'subprocess.Popen([sys.executable, "-c", '
        '"import time; time.sleep(120); print(chr(108) * 1000)"], stdout=subprocess.PIPE)\n'
        "sys.stdout.write('leader-done')\n"
        "sys.stdout.flush()\n"
    )
    _start_job(home, code=child_code)
    job_dir = _job_dir(home, VALID_JOB_ID)
    record_path = job_dir / "record.json"
    deadline = time.monotonic() + 45
    record: dict[str, Any] = {}
    while time.monotonic() < deadline:
        raw = json.loads(record_path.read_text(encoding="utf-8"))
        if raw.get("finishedAt") is not None:
            record = raw
            break
        time.sleep(0.2)
    assert record.get("state") == "failed", record
    identity = record.get("runtimeIdentity", {})
    pid, pgid = int(identity["pid"]), int(identity["pgid"])
    time.sleep(0.5)

    def group_alive() -> bool:
        try:
            os.killpg(pgid, 0)
            return True
        except ProcessLookupError:
            return False

    assert not group_alive(), "same-group descendant survived the drain-timeout kill"
    del pid


def test_gc_sweep_survives_churn_and_visits_every_stale_entry(tmp_path: Path) -> None:
    """Create + delete entries between passes; every stale job is eventually
    visited while per-pass enumeration stays within the visit budget
    (churn regression)."""
    import hashlib

    home = _home(tmp_path)
    stale_names = [f"{index:032d}" for index in range(20)]
    old = time.time() - 7200.0

    def shard_of(name: str) -> int:
        return int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], "big") % 16

    def make_stale(name: str) -> None:
        job_dir = _job_dir(home, name)
        job_dir.mkdir(parents=True)
        record_path = job_dir / "record.json"
        record_path.write_text(
            json.dumps({"jobId": name, "state": "succeeded", "finishedAt": old - 5.0})
        )
        os.utime(record_path, (old, old))
        os.utime(job_dir, (old, old))

    for name in stale_names:
        make_stale(name)

    removed, visited = 0, 0
    for shard_pass in range(48):
        summary = _run_helper(
            {
                "operation": "gc",
                "retention_seconds": 5,
                "grace_seconds": 0,
                "max_entries": 3,
                "shards": 16,
                "shard": shard_pass % 16,
            },
            home,
        )
        assert summary["visited"] <= 64
        assert summary["scanned"] <= 3
        removed += summary["removed"]
        visited += summary["scanned"]
        # churn between passes: delete one queued stale entry, add another
        if shard_pass % 4 == 0 and removed < len(stale_names):
            victim = stale_names[(removed + 2) % len(stale_names)]
            victim_dir = _job_dir(home, victim)
            if victim_dir.exists():
                import shutil as _shutil

                _shutil.rmtree(victim_dir, ignore_errors=True)
                removed += 0
                make_stale(f"new{shard_pass:030d}")
    still_stale = []
    for entry in os.scandir(_job_root(home)):
        record_path = Path(entry.path) / "record.json"
        if record_path.exists():
            data = json.loads(record_path.read_text(encoding="utf-8"))
            if data.get("state") == "succeeded" and (time.time() - old) > 5:
                still_stale.append(entry.name)
    assert still_stale == [], still_stale
    assert visited >= len(stale_names)


def test_gc_queue_with_traversal_names_fails_closed(tmp_path: Path) -> None:

    home = _home(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir(parents=True)
    (outside / "precious.txt").write_text("keep", encoding="utf-8")

    valid = "v" * 32
    job_dir = _job_dir(home, valid)
    job_dir.mkdir(parents=True)
    record_path = job_dir / "record.json"
    old = time.time() - 3600.0
    record_path.write_text(
        json.dumps({"jobId": valid, "state": "succeeded", "finishedAt": old - 5.0})
    )
    os.utime(record_path, (old, old))
    os.utime(job_dir, (old, old))

    poison = json.dumps(["../outside", "/etc", valid])
    queue_path = _job_root(home) / f".gc-queue-{_shard_of(valid)}"
    queue_path.write_text(poison, encoding="utf-8")

    summary = _run_helper(
        {
            "operation": "gc",
            "retention_seconds": 5,
            "grace_seconds": 0,
            "max_entries": 3,
            "shard": _shard_of(valid),
        },
        home,
    )
    assert list(_job_root(home).glob(".gc-queue-*")) == [queue_path]
    assert not (_job_root(home) / "../outside").exists()
    assert (outside / "precious.txt").read_text() == "keep"
    assert summary["removed"] == 1
    assert _job_dir(home, valid).exists() is False
    assert summary["visited"] <= 64
    assert queue_path.exists()
    assert queue_path.read_text(encoding="utf-8") == poison


def test_gc_sweep_skips_malformed_same_shard_entries(tmp_path: Path) -> None:
    """Sweep regression: a malformed same-shard entry is never counted as
    enumerated, never touched destructively, and inflates only the visit
    budget — no queue write, no repeated full enumeration."""
    home = _home(tmp_path)
    malformed = "not-a-valid-job-id"
    anchor = "a" * 32
    job_ids = [
        candidate * 32
        for candidate in "abcdefghij"
        if _shard_of(candidate * 32) == _shard_of(anchor)
    ][:2]
    stale = time.time() - 3600.0
    shard_zero = _shard_of(anchor)
    malformed_bucket = _bucket_of(malformed)
    malformed_leaf = (
        _job_root(home)
        / f"s{shard_zero:x}"
        / f"b{malformed_bucket >> 8:x}"
        / f"c{malformed_bucket & 0xFF:x}"
    )
    (malformed_leaf / malformed).mkdir(parents=True)
    for job_id in job_ids:
        job_dir = _job_dir(home, job_id)
        job_dir.mkdir(parents=True)
        record_path = job_dir / "record.json"
        record_path.write_text(
            json.dumps({"jobId": job_id, "state": "succeeded", "finishedAt": stale - 5.0})
        )
        os.utime(record_path, (stale, stale))
        os.utime(job_dir, (stale, stale))

    shard = _shard_of(job_ids[0])
    summary = _run_helper(
        {
            "operation": "gc",
            "retention_seconds": 5,
            "grace_seconds": 0,
            "max_entries": 256,
            "shard": shard,
        },
        home,
    )
    assert summary["visited"] == len(job_ids)
    assert summary["removed"] == len(job_ids)
    assert summary["enumerated"] == len(job_ids)
    assert summary["iterated"] >= len(job_ids) + 1
    assert (malformed_leaf / malformed).exists()
    assert list(_job_root(home).glob(".gc-queue-*")) == []

    second = _run_helper(
        {
            "operation": "gc",
            "retention_seconds": 5,
            "grace_seconds": 0,
            "max_entries": 256,
            "shard": shard,
        },
        home,
    )
    assert second["visited"] == 0
    assert second["iterated"] >= 1
    assert second["enumerated"] == 0
    assert second["removed"] == 0
    assert (malformed_leaf / malformed).exists()
    assert list(_job_root(home).glob(".gc-queue-*")) == []


def test_gc_stays_bounded_when_legacy_queue_size_cap_is_exceeded(
    tmp_path: Path,
) -> None:
    """Supervisor round-9 regression: with enough same-shard entries to exceed
    the historical 1 MiB serialized-queue read cap, the sweep must stay
    bounded per pass and must never create any serialized queue, so the
    oversized -> reject -> full rebuild -> oversized cycle is impossible."""
    home = _home(tmp_path)

    def shard_of(name: str) -> int:
        return int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], "big") % 16

    names: list[str] = []
    index = 0
    while len(names) < 26_000:
        candidate = f"{index:032d}"
        index += 1
        if shard_of(candidate) == 0:
            names.append(candidate)
    old = time.time() - 7200.0
    for name in names:
        job_dir = _job_dir(home, name)
        job_dir.mkdir(parents=True)
        record_path = job_dir / "record.json"
        record_path.write_text(
            json.dumps({"jobId": name, "state": "succeeded", "finishedAt": old - 5.0})
        )
        os.utime(record_path, (old, old))
        os.utime(job_dir, (old, old))

    payload = {
        "operation": "gc",
        "retention_seconds": 5,
        "grace_seconds": 3600,
        "max_entries": 3,
        "shards": 16,
        "shard": 0,
    }
    first = _run_helper(payload, home)
    assert first["visited"] == 64
    assert first["removed"] == 3
    assert first["errors"] == 0
    second = _run_helper(payload, home)
    assert second["visited"] == 64
    assert second["removed"] == 3
    assert second["errors"] == 0
    assert list(_job_root(home).glob(".gc-queue-*")) == []


def test_gc_cursor_prevents_starvation_behind_stable_front(tmp_path: Path) -> None:
    """Greptile P1 regression: a stable front of recent entries larger than
    the visit budget cannot starve stale entries that follow it. The
    per-shard cursor advances through the directory across passes until the
    stale tail is collected, while every pass stays within the budgets."""
    home = _home(tmp_path)
    stale_names: list[str] = []
    index = 0
    while len(stale_names) < 4:
        candidate = f"{index:032d}"
        index += 1
        if _shard_of(candidate) == 0:
            stale_names.append(candidate)
    front_names: list[str] = []
    while len(front_names) < 200:
        candidate = f"{index:032d}"
        index += 1
        if _shard_of(candidate) == 0:
            front_names.append(candidate)

    old = time.time() - 7200.0
    for name in front_names:
        _job_dir(home, name).mkdir(parents=True)
    for name in stale_names:
        job_dir = _job_dir(home, name)
        job_dir.mkdir(parents=True)
        record_path = job_dir / "record.json"
        record_path.write_text(
            json.dumps({"jobId": name, "state": "succeeded", "finishedAt": old - 5.0})
        )
        os.utime(record_path, (old, old))
        os.utime(job_dir, (old, old))

    payload = {
        "operation": "gc",
        "retention_seconds": 5,
        "grace_seconds": 3600,
        "max_entries": 3,
        "shards": 16,
        "shard": 0,
    }
    first = _run_helper(payload, home)
    assert first["visited"] <= 64
    assert first["scanned"] <= 3

    removed_total = first["removed"]
    collected = False
    for _ in range(8):
        summary = _run_helper(payload, home)
        assert summary["visited"] <= 64
        assert summary["scanned"] <= 3
        assert summary["errors"] == 0
        removed_total += summary["removed"]
        if removed_total >= len(stale_names):
            collected = True
            break
    assert collected, f"stale entries starved: removed_total={removed_total}"
    for name in stale_names:
        assert _job_dir(home, name).exists() is False
    for name in front_names:
        assert _job_dir(home, name).exists()


def test_gc_cursor_survives_corruption_and_symlink(tmp_path: Path) -> None:
    """A corrupt or symlinked cursor is tolerated as offset zero and never
    followed; cleanup still makes progress."""
    home = _home(tmp_path)
    stale = "c" * 32
    job_dir = _job_dir(home, stale)
    job_dir.mkdir(parents=True)
    record_path = job_dir / "record.json"
    old = time.time() - 7200.0
    record_path.write_text(
        json.dumps({"jobId": stale, "state": "succeeded", "finishedAt": old - 5.0})
    )
    os.utime(record_path, (old, old))
    os.utime(job_dir, (old, old))

    job_shard = _shard_of(stale)
    corrupt = _job_root(home) / f".gc-cursor-{job_shard:x}"
    corrupt.write_text("not-a-number", encoding="utf-8")
    summary = _run_helper(
        {
            "operation": "gc",
            "retention_seconds": 5,
            "grace_seconds": 0,
            "max_entries": 3,
            "shards": 16,
            "shard": job_shard,
        },
        home,
    )
    assert summary["removed"] == 1

    symlinked = _job_root(home) / f".gc-cursor-{job_shard:x}"
    if symlinked.exists() or symlinked.is_symlink():
        symlinked.unlink()
    symlinked.symlink_to("/etc/hostname")
    link_name = "d" * 32
    index = 0
    while _shard_of(link_name) != job_shard:
        link_name = f"d{index:031d}"
        index += 1
    dir_link = str(_job_dir(home, link_name))
    Path(dir_link).parent.mkdir(parents=True, exist_ok=True)
    os.symlink("/etc", dir_link)
    os.utime(dir_link, (old, old), follow_symlinks=False)
    second = _run_helper(
        {
            "operation": "gc",
            "retention_seconds": 5,
            "grace_seconds": 0,
            "max_entries": 3,
            "shards": 16,
            "shard": job_shard,
        },
        home,
    )
    assert second["removed"] >= 1
    assert os.path.islink(dir_link) is False
    assert os.path.isdir("/etc")


def test_gc_trie_cursor_advances_past_4096_survivors(tmp_path: Path) -> None:
    """Round-10 regression A: with more than 4096 stable survivor entries and
    a stale tail behind them, repeated invocations must eventually collect
    the tail while every pass stays within the documented visit, yield, and
    removal bounds — the ordinal replay cannot stall at the old budget."""
    home = _home(tmp_path)
    survivors: list[str] = []
    index = 0
    while len(survivors) < 4100:
        candidate = f"{index:032d}"
        index += 1
        if _shard_of(candidate) == 0:
            survivors.append(candidate)
    for name in survivors:
        _job_dir(home, name).mkdir(parents=True)

    stale_names: list[str] = []
    while len(stale_names) < 4:
        candidate = f"{index:032d}"
        index += 1
        if _shard_of(candidate) == 0:
            stale_names.append(candidate)
    old = time.time() - 7200.0
    for name in stale_names:
        job_dir = _job_dir(home, name)
        job_dir.mkdir(parents=True)
        record_path = job_dir / "record.json"
        record_path.write_text(
            json.dumps({"jobId": name, "state": "succeeded", "finishedAt": old - 5.0})
        )
        os.utime(record_path, (old, old))
        os.utime(job_dir, (old, old))

    payload = {
        "operation": "gc",
        "retention_seconds": 5,
        "grace_seconds": 3600,
        "max_entries": 64,
        "shards": 16,
        "shard": 0,
    }
    removed_total = 0
    collected = False
    for _ in range(30):
        summary = _run_helper(payload, home)
        assert summary["visited"] <= 256
        assert summary["iterated"] <= 4096
        assert summary["scanned"] <= 64
        assert summary["errors"] == 0
        removed_total += summary["removed"]
        if removed_total >= len(stale_names):
            collected = True
            break
    assert collected, f"stale tail starved past 4096 survivors: {removed_total}"
    for name in stale_names:
        assert _job_dir(home, name).exists() is False
    for name in survivors[:50]:
        assert _job_dir(home, name).exists()


def test_gc_cursor_at_ordinal_boundary_makes_progress(tmp_path: Path) -> None:
    """Round-10 regression A2: a persisted cursor parked at the previous
    4096-yield boundary must perform new useful work on the next pass
    instead of replaying the skip forever (visited == 0 forever)."""
    home = _home(tmp_path)
    stale_names: list[str] = []
    index = 0
    while len(stale_names) < 2:
        candidate = f"{index:032d}"
        index += 1
        if _shard_of(candidate) == 0:
            stale_names.append(candidate)
    old = time.time() - 7200.0
    for name in stale_names:
        job_dir = _job_dir(home, name)
        job_dir.mkdir(parents=True)
        record_path = job_dir / "record.json"
        record_path.write_text(
            json.dumps({"jobId": name, "state": "succeeded", "finishedAt": old - 5.0})
        )
        os.utime(record_path, (old, old))
        os.utime(job_dir, (old, old))

    cursor_path = _job_root(home) / ".gc-cursor-0"
    cursor_path.write_text(
        json.dumps({"b": _bucket_of(stale_names[0]), "o": 4095}), encoding="utf-8"
    )

    payload = {
        "operation": "gc",
        "retention_seconds": 5,
        "grace_seconds": 3600,
        "max_entries": 3,
        "shards": 16,
        "shard": 0,
    }
    saw_new_work = False
    collected = False
    removed_total = 0
    for _ in range(16):
        summary = _run_helper(payload, home)
        assert summary["visited"] <= 64
        assert summary["iterated"] <= 4096
        if summary["visited"] > 0:
            saw_new_work = True
        removed_total += summary["removed"]
        if removed_total >= len(stale_names):
            collected = True
            break
    assert saw_new_work, "cursor replay never returned to useful work"
    assert collected, f"stale entries never collected: {removed_total}"


def test_gc_rotation_reaches_every_shard_at_fixed_time(tmp_path: Path) -> None:
    """Round-10 regression B: defaulted invocations rotate through shards
    via the durable counter, so an unlucky start cadence cannot starve
    shards the way floor(time/60) % shards could."""
    home = _home(tmp_path)
    seen: list[int] = []
    for _ in range(16):
        summary = _run_helper(
            {
                "operation": "gc",
                "retention_seconds": 5,
                "grace_seconds": 0,
                "max_entries": 3,
                "shards": 16,
            },
            home,
        )
        seen.append(summary["shard"])
    assert sorted(seen) == list(range(16))

    second_sweep = []
    for _ in range(16):
        summary = _run_helper(
            {
                "operation": "gc",
                "retention_seconds": 5,
                "grace_seconds": 0,
                "max_entries": 3,
                "shards": 16,
            },
            home,
        )
        second_sweep.append(summary["shard"])
    assert sorted(second_sweep) == list(range(16))


def test_gc_cursor_advances_past_fresh_prefix_within_leaf(tmp_path: Path) -> None:
    """Round-10 Greptile follow-up: a leaf holding more fresh survivors than
    the visit budget must not trap the cursor on the same prefix — the
    ordinal records positions consumed, so stale jobs stored after the
    survivors are reached on the following pass."""
    home = _home(tmp_path)
    leaf_bucket = 0x1A0B
    leaf = _job_root(home) / "s0" / f"b{leaf_bucket >> 8:x}" / f"c{leaf_bucket & 0xFF:x}"
    leaf.mkdir(parents=True, exist_ok=True)

    names: list[str] = []
    index = 0
    while len(names) < 67:
        candidate = f"{index:032d}"
        index += 1
        if _shard_of(candidate) == 0:
            names.append(candidate)
    for name in names:
        _job_dir(home, name).mkdir(parents=True, exist_ok=True)
        shutil.move(str(_job_dir(home, name)), str(leaf / name))

    order = os.listdir(leaf)
    assert len(order) == 67
    survivors, stale_group = order[:64], order[64:]
    old = time.time() - 7200.0
    for name in stale_group:
        job_dir = leaf / name
        record_path = job_dir / "record.json"
        record_path.write_text(
            json.dumps({"jobId": name, "state": "succeeded", "finishedAt": old - 5.0})
        )
        os.utime(record_path, (old, old))
        os.utime(job_dir, (old, old))

    payload = {
        "operation": "gc",
        "retention_seconds": 5,
        "grace_seconds": 3600,
        "max_entries": 3,
        "shards": 16,
        "shard": 0,
    }
    first = _run_helper(payload, home)
    assert first["visited"] == 64
    assert first["removed"] == 0

    removed_total = first["removed"]
    passes = 1
    while removed_total < len(stale_group) and passes < 8:
        summary = _run_helper(payload, home)
        removed_total += summary["removed"]
        passes += 1
    assert removed_total >= len(stale_group)
    for name in stale_group:
        assert (leaf / name).exists() is False
    for name in survivors:
        assert (leaf / name).exists()


def test_documented_gc_bounds_match_implementation(tmp_path: Path) -> None:
    """Round-10 regression C: the README documents the exact hard bounds the
    sweep enforces; the same constants must be observable in behavior and
    present verbatim in the documentation."""
    readme = Path(__file__).resolve().parents[2] / "README.md"
    text = readme.read_text(encoding="utf-8")
    assert "`max_entries` (default 256)" in text
    assert "`max(64, 4 x max_entries)`" in text
    assert "`max(4096, 4 x max_entries)`" in text

    home = _home(tmp_path)
    names: list[str] = []
    index = 0
    while len(names) < 2000:
        candidate = f"{index:032d}"
        index += 1
        if _shard_of(candidate) == 0:
            names.append(candidate)
    for name in names:
        _job_dir(home, name).mkdir(parents=True)
    summary = _run_helper(
        {
            "operation": "gc",
            "retention_seconds": 5,
            "grace_seconds": 3600,
            "max_entries": 3,
            "shards": 16,
            "shard": 0,
        },
        home,
    )
    assert summary["visited"] == 64
    assert summary["iterated"] <= 4096
    assert summary["scanned"] <= 3


def test_gc_rejects_bucket_symlink_traversal(tmp_path: Path) -> None:
    """Round-10 Greptile P1 regression: a "b" symlink planted under a managed
    shard is never followed — its target directory keeps its contents and
    the sweep stays inside the managed root."""
    home = _home(tmp_path)
    stale = "e" * 32
    job_dir = _job_dir(home, stale)
    job_dir.mkdir(parents=True)
    record_path = job_dir / "record.json"
    old = time.time() - 7200.0
    record_path.write_text(
        json.dumps({"jobId": stale, "state": "succeeded", "finishedAt": old - 5.0})
    )
    os.utime(record_path, (old, old))
    os.utime(job_dir, (old, old))

    outside = tmp_path / "victim"
    victim_job = outside / "victim-job"
    victim_job.mkdir(parents=True)
    (victim_job / "record.json").write_text(
        json.dumps({"jobId": "victim-job", "state": "succeeded", "finishedAt": 0})
    )

    shard_root = _job_root(home) / f"s{_shard_of(stale):x}"
    link_bucket = (0x1A0B >> 8) ^ 0xFF
    link_path = shard_root / f"b{link_bucket:x}"
    os.symlink(outside, link_path)

    summary = _run_helper(
        {
            "operation": "gc",
            "retention_seconds": 5,
            "grace_seconds": 0,
            "max_entries": 3,
            "shards": 16,
            "shard": _shard_of(stale),
        },
        home,
    )
    # The planted symlink itself is evicted as junk (never followed), the
    # victim directory keeps its contents, and normal cleanup proceeds.
    assert summary["removed"] == 2
    assert link_path.is_symlink() is False
    assert (victim_job / "record.json").exists()
    assert (outside / "victim-job").exists()
    assert _job_dir(home, stale).exists() is False


def test_gc_level_scans_stay_bounded_under_junk_entries(tmp_path: Path) -> None:
    """Round-10 Greptile P2 regression: thousands of malformed entries in a
    shard directory cannot make a cleanup pass unbounded — level scans are
    capped at the same readdir-yield budget as leaf iteration."""
    home = _home(tmp_path)
    shard_root = _job_root(home) / "s0"
    shard_root.mkdir(parents=True, exist_ok=True)
    junk = shard_root / "junk-payload"
    junk.mkdir()
    for index in range(6000):
        (junk / f"pad{index:04d}").write_text("x", encoding="utf-8")

    valid = "f" * 32
    job_dir = _job_dir(home, valid)
    job_dir.mkdir(parents=True, exist_ok=True)
    record_path = job_dir / "record.json"
    old = time.time() - 7200.0
    record_path.write_text(
        json.dumps({"jobId": valid, "state": "succeeded", "finishedAt": old - 5.0})
    )
    os.utime(record_path, (old, old))
    os.utime(job_dir, (old, old))

    summary = _run_helper(
        {
            "operation": "gc",
            "retention_seconds": 5,
            "grace_seconds": 3600,
            "max_entries": 3,
            "shards": 16,
            "shard": 0,
        },
        home,
    )
    assert summary["iterated"] <= 3 * 4096
    assert summary["errors"] == 0


def test_gc_eviction_clears_junk_prefix_blocking_bucket_discovery(
    tmp_path: Path,
) -> None:
    """Round-10 Greptile follow-up regression: a shard directory whose
    readdir order is dominated by thousands of junk entries must not starve
    valid buckets forever — junk files are evicted within the per-pass
    budgets until the valid bucket is discovered and its stale tail
    collected."""
    home = _home(tmp_path)
    shard_root = _job_root(home) / "s0"
    shard_root.mkdir(parents=True, exist_ok=True)
    junk_dir = shard_root / "junk-bucket"
    junk_dir.mkdir()
    for index in range(4096):
        (junk_dir / f"junk{index:04d}").write_text("x", encoding="utf-8")

    valid = None
    index = 0
    while valid is None:
        candidate = f"{index:032d}"
        index += 1
        if _shard_of(candidate) == 0:
            valid = candidate
    job_dir = _job_dir(home, valid)
    job_dir.mkdir(parents=True, exist_ok=True)
    record_path = job_dir / "record.json"
    old = time.time() - 7200.0
    record_path.write_text(
        json.dumps({"jobId": valid, "state": "succeeded", "finishedAt": old - 5.0})
    )
    os.utime(record_path, (old, old))
    os.utime(job_dir, (old, old))

    payload = {
        "operation": "gc",
        "retention_seconds": 5,
        "grace_seconds": 0,
        "max_entries": 3,
        "shards": 16,
        "shard": 0,
    }
    collected = False
    removed_total = 0
    for _ in range(10):
        summary = _run_helper(payload, home)
        assert summary["iterated"] <= 3 * 4096
        assert summary["errors"] == 0
        removed_total += summary["removed"]
        if _job_dir(home, valid).exists() is False:
            collected = True
            break
    assert collected, f"valid bucket never reached: removed={removed_total}"


def _make_flat_job(home: Path, name: str, record: dict) -> Path:
    job_dir = _job_root(home) / name
    job_dir.mkdir(parents=True)
    (job_dir / "record.json").write_text(json.dumps(record))
    return job_dir


def _run_op(operation: str, home: Path, extra: dict) -> dict:
    return _run_helper({"operation": operation, **extra}, home)


def test_legacy_flat_terminal_job_survives_upgrade(tmp_path: Path) -> None:
    home = _home(tmp_path)
    job_id = "b" * 32
    _make_flat_job(
        home,
        job_id,
        {"jobId": job_id, "state": "succeeded", "finishedAt": time.time(), "exitCode": 0},
    )
    (_job_root(home) / job_id / "stdout").write_text("legacy output")
    status = _run_op("status", home, {"job_id": job_id})
    assert status["state"] == "succeeded"
    result = _run_op("result", home, {"job_id": job_id})
    assert result["exitCode"] == 0
    output = _run_op(
        "output", home, {"job_id": job_id, "stream": "stdout", "offset": 0, "max_bytes": 1024}
    )
    assert "legacy output" in output["data"]
    assert (_job_root(home) / job_id).exists()


def test_legacy_flat_running_job_remains_discoverable(tmp_path: Path) -> None:
    home = _home(tmp_path)
    job_id = "c" * 32
    child = subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(0.2)
        stat_fields = Path(f"/proc/{child.pid}/stat").read_text("ascii").split()
        _make_flat_job(
            home,
            job_id,
            {
                "jobId": job_id,
                "state": "running",
                "runtimeIdentity": {
                    "pid": str(child.pid),
                    "pgid": str(child.pid),
                    "startTicks": stat_fields[21],
                },
            },
        )
        status = _run_op("status", home, {"job_id": job_id})
        assert status["state"] == "running"
    finally:
        child.kill()
        child.wait()


def test_legacy_flat_cancel_targets_existing_job(tmp_path: Path) -> None:
    home = _home(tmp_path)
    job_id = "d" * 32
    _make_flat_job(home, job_id, {"jobId": job_id, "state": "queued"})
    result = _run_op("cancel", home, {"job_id": job_id, "reason": "upgrade compat"})
    assert result["state"] == "cancelled"
    record = json.loads((_job_root(home) / job_id / "record.json").read_text())
    assert record["state"] == "cancelled"


def test_legacy_start_idempotency_creates_no_trie_duplicate(tmp_path: Path) -> None:
    home = _home(tmp_path)
    job_id = "e" * 32
    digest = "a" * 64
    _make_flat_job(
        home,
        job_id,
        {"jobId": job_id, "state": "running", "requestDigest": digest},
    )
    result = _run_op(
        "start",
        home,
        {
            "job_id": job_id,
            "request_digest": digest,
            "executable": "tail",
            "argv": ["-f", "/tmp/x"],
        },
    )
    assert result["jobId"] == job_id
    assert result["state"] == "running"
    bucket = _bucket_of(job_id)
    trie_dir = (
        _job_root(home) / f"s{_shard_of(job_id):x}" / f"b{bucket >> 8:x}" / f"c{bucket & 0xFF:x}"
    )
    assert not trie_dir.exists()


def test_expired_legacy_flat_terminal_is_gcd(tmp_path: Path) -> None:
    home = _home(tmp_path)
    job_id = "f" * 32
    job_dir = _make_flat_job(
        home,
        job_id,
        {"jobId": job_id, "state": "succeeded", "finishedAt": time.time() - 7200.0},
    )
    old = time.time() - 7200.0
    os.utime(job_dir, (old, old))
    summary = _run_op(
        "gc",
        home,
        {
            "retention_seconds": 5,
            "grace_seconds": 0,
            "max_entries": 64,
            "shards": 16,
            "shard": _shard_of(job_id),
        },
    )
    assert summary["removed"] == 1
    assert job_dir.exists() is False
    status = _run_op("status", home, {"job_id": job_id})
    assert status == {"error": "NOT_FOUND"}


def test_legacy_gc_bounded_with_many_flat_dirs(tmp_path: Path) -> None:
    home = _home(tmp_path)
    old = time.time() - 7200.0
    names: list[str] = []
    index = 0
    while len(names) < 2000:
        candidate = f"{index:032d}"
        index += 1
        names.append(candidate)
    for name in names:
        job_dir = _job_root(home) / name
        job_dir.mkdir(parents=True)
        record_path = job_dir / "record.json"
        record_path.write_text(
            json.dumps({"jobId": name, "state": "succeeded", "finishedAt": old - 5.0})
        )
        os.utime(record_path, (old, old))
        os.utime(job_dir, (old, old))

    payload = {
        "operation": "gc",
        "retention_seconds": 5,
        "grace_seconds": 3600,
        "max_entries": 3,
        "shards": 16,
        "shard": 0,
    }
    first = _run_helper(payload, home)
    assert first["iterated"] <= 4096 + 1024 + 64
    assert first["removed"] <= 3
    assert first["errors"] == 0
    second = _run_helper(payload, home)
    assert second["iterated"] <= 4096 + 1024 + 64
    assert first["removed"] + second["removed"] >= 2


def test_live_legacy_running_job_is_not_gcd(tmp_path: Path) -> None:
    home = _home(tmp_path)
    job_id = "g" * 32
    child = subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(0.2)
        stat_fields = Path(f"/proc/{child.pid}/stat").read_text("ascii").split()
        job_dir = _make_flat_job(
            home,
            job_id,
            {
                "jobId": job_id,
                "state": "running",
                "runtimeIdentity": {
                    "pid": str(child.pid),
                    "pgid": str(child.pid),
                    "startTicks": stat_fields[21],
                },
            },
        )
        os.utime(job_dir, (time.time() - 7200,) * 2)
        summary = _run_op(
            "gc",
            home,
            {
                "retention_seconds": 5,
                "grace_seconds": 0,
                "max_entries": 64,
                "shards": 16,
                "shard": _shard_of(job_id),
            },
        )
        assert job_dir.exists()
        assert summary["keptActive"] >= 1
    finally:
        child.kill()
        child.wait()


def test_legacy_symlink_cannot_escape_root(tmp_path: Path) -> None:
    home = _home(tmp_path)
    job_id = "h" * 32
    outside = tmp_path / "outside-target"
    outside.mkdir()
    (outside / "precious.txt").write_text("keep")
    link = _job_root(home) / job_id
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside, target_is_directory=True)

    status = _run_op("status", home, {"job_id": job_id})
    assert status == {"error": "VALIDATION_FAILED"}
    assert (outside / "precious.txt").read_text() == "keep"

    old = time.time() - 7200.0
    os.utime(link, (old, old), follow_symlinks=False)
    summary = _run_op(
        "gc",
        home,
        {
            "retention_seconds": 5,
            "grace_seconds": 0,
            "max_entries": 64,
            "shards": 16,
            "shard": _shard_of(job_id),
        },
    )
    assert summary["removed"] >= 1
    assert link.exists() is False and not link.is_symlink()
    assert (outside / "precious.txt").read_text() == "keep"


def test_legacy_sweep_reaches_expired_job_behind_retained_prefix(
    tmp_path: Path,
) -> None:
    """Round-11 Greptile regression: expired legacy jobs stored behind more
    retained legacy entries than any per-pass cap are still collected,
    because the frozen flat corpus is read in full each invocation."""
    home = _home(tmp_path)
    retained: list[str] = []
    expired: list[str] = []
    index = 0
    while len(retained) < 1024 or len(expired) < 1:
        candidate = f"{index:032d}"
        index += 1
        if len(retained) < 1024:
            retained.append(candidate)
        elif len(expired) < 1:
            expired.append(candidate)
    old = time.time() - 7200.0
    now = time.time()
    for name in retained:
        job_dir = _job_root(home) / name
        job_dir.mkdir(parents=True)
        record_path = job_dir / "record.json"
        record_path.write_text(json.dumps({"jobId": name, "state": "succeeded", "finishedAt": now}))
    for name in expired:
        job_dir = _job_root(home) / name
        job_dir.mkdir(parents=True)
        record_path = job_dir / "record.json"
        record_path.write_text(
            json.dumps({"jobId": name, "state": "succeeded", "finishedAt": old - 5.0})
        )
        os.utime(record_path, (old, old))
        os.utime(job_dir, (old, old))

    payload = {
        "operation": "gc",
        "retention_seconds": 5,
        "grace_seconds": 0,
        "max_entries": 3,
        "shards": 16,
        "shard": 0,
    }
    collected = False
    for _ in range(6):
        summary = _run_helper(payload, home)
        assert summary["errors"] == 0
        if all((_job_root(home) / n).exists() is False for n in expired):
            collected = True
            break
    assert collected, "expired legacy job starved behind retained prefix"
    for name in retained:
        assert (_job_root(home) / name).exists()


def test_legacy_index_discovers_post_snapshot_flat_jobs(tmp_path: Path) -> None:
    """Round-11 Greptile regression: a flat-layout job created after the
    legacy index was built (rolling-upgrade writer) is folded into the
    index by the capped discovery scan and collected — not left to persist
    while retained indexed entries keep the index non-empty."""
    home = _home(tmp_path)
    retained = "5" * 32
    job_dir = _job_root(home) / retained
    job_dir.mkdir(parents=True)
    now = time.time()
    (job_dir / "record.json").write_text(
        json.dumps({"jobId": retained, "state": "succeeded", "finishedAt": now})
    )

    payload = {
        "operation": "gc",
        "retention_seconds": 5,
        "grace_seconds": 0,
        "max_entries": 3,
        "shards": 16,
        "shard": 0,
    }
    first = _run_helper(payload, home)
    del first
    index_path = _job_root(home) / ".gc-legacy-index"
    assert index_path.exists()

    expired = "6" * 32
    expired_dir = _job_root(home) / expired
    expired_dir.mkdir(parents=True)
    old = time.time() - 7200.0
    record_path = expired_dir / "record.json"
    record_path.write_text(
        json.dumps({"jobId": expired, "state": "succeeded", "finishedAt": old - 5.0})
    )
    os.utime(record_path, (old, old))
    os.utime(expired_dir, (old, old))

    collected = False
    for _ in range(6):
        summary = _run_helper(payload, home)
        assert summary["errors"] == 0
        if expired_dir.exists() is False:
            collected = True
            break
    assert collected, "post-snapshot expired legacy job never collected"
    assert job_dir.exists()


def test_legacy_discovery_not_starved_by_indexed_prefix(tmp_path: Path) -> None:
    """Round-11 Greptile regression: an indexed prefix larger than the
    discovery budget cannot hide a newly created flat job — indexed, dot,
    and trie-level entries are skipped without consuming the discovery
    budget, so the new job is discovered, indexed, and collected."""
    home = _home(tmp_path)
    retained_prefix: list[str] = []
    index2 = 0
    while len(retained_prefix) < 4400:
        candidate = f"{index2:032d}"
        index2 += 1
        retained_prefix.append(candidate)
    now = time.time()
    for name in retained_prefix:
        job_dir = _job_root(home) / name
        job_dir.mkdir(parents=True)
        (job_dir / "record.json").write_text(
            json.dumps({"jobId": name, "state": "succeeded", "finishedAt": now})
        )
    # Build the index containing all of the prefix entries.
    payload = {
        "operation": "gc",
        "retention_seconds": 5,
        "grace_seconds": 0,
        "max_entries": 3,
        "shards": 16,
        "shard": 0,
    }
    _run_helper(payload, home)

    expired = "7" * 32
    expired_dir = _job_root(home) / expired
    expired_dir.mkdir(parents=True)
    old = time.time() - 7200.0
    record_path = expired_dir / "record.json"
    record_path.write_text(
        json.dumps({"jobId": expired, "state": "succeeded", "finishedAt": old - 5.0})
    )
    os.utime(record_path, (old, old))
    os.utime(expired_dir, (old, old))

    collected = False
    for _ in range(6):
        summary = _run_helper(payload, home)
        assert summary["errors"] == 0
        if expired_dir.exists() is False:
            collected = True
            break
    assert collected, "new flat job starved behind indexed prefix"
