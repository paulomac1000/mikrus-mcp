"""Bounded SSH adapter with stable identity verification."""

from __future__ import annotations

import asyncio
import json
import logging
import shlex
import textwrap
from typing import Any

from mikrus_mcp.clients.common import _remote_atomic_write_command, _remote_read_prefix
from mikrus_mcp.clients.mikrus import MikrusClient
from mikrus_mcp.config import TargetConfig
from mikrus_mcp.errors import AppError, ErrorCode
from mikrus_mcp.tools.constants import (
    EXEC_HTTP_TIMEOUT,
    MAX_JOURNAL_LINES,
    MAX_PROCESS_OUTPUT_BYTES,
    MAX_SEARCH_RESULTS,
    SSH_DEFAULT_TIMEOUT,
)
from mikrus_mcp.validators import (
    ValidationError,
    validate_container_name,
    validate_hours_param,
    validate_lines_param,
    validate_port,
    validate_process_target,
    validate_search_pattern,
    validate_service_action,
    validate_service_name,
)

logger = logging.getLogger(__name__)

SSH_TERMINATE_WAIT_SECONDS = 5.0
_PROGRAM_HELPER = textwrap.dedent(
    """
    import json, os, select, signal, subprocess, sys
    LIMIT = 512 * 1024
    payload = json.load(sys.stdin)
    child = subprocess.Popen(
        [payload["executable"], *payload["argv"]],
        cwd=payload.get("cwd"),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    def kill_child():
        try:
            os.killpg(os.getpgid(child.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait()
    def stop(*_):
        kill_child()
        raise SystemExit(143)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    os.set_blocking(child.stdin.fileno(), False)
    os.set_blocking(child.stdout.fileno(), False)
    os.set_blocking(child.stderr.fileno(), False)
    stdin_data = (payload.get("stdin") or "").encode()
    stdin_sent = 0
    stdin_open = True
    streams = {child.stdout: "output", child.stderr: "stderr"}
    chunks = {"output": [], "stderr": []}
    total = 0
    truncated = False
    while streams or stdin_open:
        readable = list(streams)
        writable = [child.stdin] if stdin_open else []
        ready, writable_ready, _ = select.select(readable, writable, [], 0.25)
        for stream in ready:
            try:
                data = stream.read(8192)
            except (BlockingIOError, OSError):
                continue
            if not data:
                del streams[stream]
                continue
            total += len(data)
            collected = sum(len(item) for values in chunks.values() for item in values)
            remaining = max(0, LIMIT - collected)
            if remaining:
                chunks[streams[stream]].append(data[:remaining])
            if total > LIMIT:
                truncated = True
                kill_child()
                print(json.dumps({
                    "output": b"".join(chunks["output"]).decode(errors="replace"),
                    "stderr": b"".join(chunks["stderr"]).decode(errors="replace"),
                    "exit_code": child.returncode,
                    "truncated": True,
                }))
                raise SystemExit(0)
        if stdin_open and child.stdin in writable_ready:
            if stdin_sent < len(stdin_data):
                try:
                    stdin_sent += os.write(
                        child.stdin.fileno(), stdin_data[stdin_sent:stdin_sent + 8192]
                    )
                except BlockingIOError:
                    pass
                except OSError:
                    stdin_open = False
            if stdin_sent >= len(stdin_data):
                try:
                    child.stdin.close()
                except OSError:
                    pass
                stdin_open = False
    code = child.wait()
    print(json.dumps({
        "output": b"".join(chunks["output"]).decode(errors="replace"),
        "stderr": b"".join(chunks["stderr"]).decode(errors="replace"),
        "exit_code": code,
        "truncated": truncated,
    }))
    """
).strip()

_REMOTE_JOB_HELPER = textwrap.dedent(
    """
    import fcntl, hashlib, json, os, re, signal, subprocess, sys, tempfile, time
    from pathlib import Path
    from pathlib import Path as PathLib
    LIMIT = 1024 * 1024
    JOB_ID = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
    payload = json.load(sys.stdin)
    job_id = payload.get("job_id", "")
    if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
        raise SystemExit("invalid job id")
    root = Path.home() / ".cache" / "mikrus-mcp" / "remote-jobs"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    job_dir = root / job_id
    meta_path = job_dir / "record.json"
    stdout_path = job_dir / "stdout"
    stderr_path = job_dir / "stderr"
    if job_dir.is_symlink() or (job_dir.exists() and not job_dir.is_dir()):
        print(json.dumps({"error": "VALIDATION_FAILED"}))
        raise SystemExit(0)
    def read_record():
        return json.loads(meta_path.read_text(encoding="utf-8"))
    def write_record(record):
        fd, name = tempfile.mkstemp(prefix=".record.", dir=job_dir)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(record, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, meta_path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
    def output(path, offset, maximum):
        data = path.read_bytes() if path.exists() else b""
        chunk = data[offset:offset + maximum]
        return {
            "data": chunk.decode(errors="replace"),
            "next_offset": offset + len(chunk),
            "eof": offset + len(chunk) >= len(data),
        }
    def start_ticks(pid):
        try:
            fields = Path(f"/proc/{pid}/stat").read_text(encoding="ascii").split()
            return fields[21]
        except (OSError, IndexError, ValueError):
            return None
    operation = payload.get("operation")
    if operation == "start":
        job_dir.mkdir(mode=0o700, parents=False, exist_ok=False) if not job_dir.exists() else None
        if meta_path.exists():
            record = read_record()
            if record.get("requestDigest") != payload.get("request_digest"):
                print(json.dumps({"error": "IDEMPOTENCY_CONFLICT"}))
                raise SystemExit(0)
            print(json.dumps(record))
            raise SystemExit(0)
        record = {
            "jobId": job_id,
            "state": "queued",
            "requestDigest": payload["request_digest"],
            "createdAt": time.time(),
            "safeToRetry": False,
            "payload": {
                "executable": payload["executable"],
                "argv": payload["argv"],
                "cwd": payload.get("cwd"),
                "stdin": payload.get("stdin"),
            },
        }
        write_record(record)
        worker = os.environ.copy()
        worker["MIKRUS_REMOTE_JOB_META"] = str(meta_path)
        subprocess.Popen(
            ["python3", "-c", payload["worker"]],
            env=worker,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
        print(json.dumps(read_record()))
    elif operation in {"status", "result", "output", "cancel"}:
        if not meta_path.is_file() or meta_path.is_symlink():
            print(json.dumps({"error": "NOT_FOUND"}))
            raise SystemExit(0)
        record = read_record()
        if operation == "output":
            stream = payload.get("stream")
            path = (
                stdout_path
                if stream == "stdout"
                else stderr_path
                if stream == "stderr"
                else None
            )
            if path is None:
                print(json.dumps({"error": "VALIDATION_FAILED"}))
            else:
                print(
                    json.dumps(
                        output(
                            path,
                            int(payload.get("offset", 0)),
                            int(payload.get("max_bytes", LIMIT)),
                        )
                    )
                )
        elif operation == "cancel":
            lock_path = meta_path.with_name(meta_path.name + ".lock")
            nofollow = getattr(os, "O_NOFOLLOW", 0)
            cancel_lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | nofollow, 0o600)
            os.fchmod(cancel_lock_fd, 0o600)
            fcntl.flock(cancel_lock_fd, fcntl.LOCK_EX)
            record = read_record()
            identity = record.get("runtimeIdentity", {})
            pgid = identity.get("pgid") if isinstance(identity, dict) else None
            pid = identity.get("pid") if isinstance(identity, dict) else None
            expected_ticks = identity.get("startTicks") if isinstance(identity, dict) else None
            try:
                numeric_pid = int(pid)
            except (TypeError, ValueError):
                numeric_pid = None
            try:
                numeric_pgid = int(pgid)
            except (TypeError, ValueError):
                numeric_pgid = None
            if record.get("state") == "queued" and identity == {}:
                record["state"] = "cancelled"
                write_record(record)
                fcntl.flock(cancel_lock_fd, fcntl.LOCK_UN)
                os.close(cancel_lock_fd)
                print(json.dumps(record))
                raise SystemExit(0)
            if (
                numeric_pid is None
                or numeric_pgid is None
                or not isinstance(expected_ticks, str)
            ):
                fcntl.flock(cancel_lock_fd, fcntl.LOCK_UN)
                os.close(cancel_lock_fd)
                print(json.dumps({"error": "CONFLICT", "detail": "malformed runtime identity"}))
                raise SystemExit(0)
            if expected_ticks != start_ticks(numeric_pid):
                fcntl.flock(cancel_lock_fd, fcntl.LOCK_UN)
                os.close(cancel_lock_fd)
                print(json.dumps({"error": "CONFLICT"}))
                raise SystemExit(0)
            if True:
                try:
                    os.killpg(numeric_pgid, signal.SIGTERM)
                except OSError:
                    pass
            def leader_alive():
                if numeric_pid is None:
                    return False
                try:
                    fields = (
                        PathLib(f"/proc/{numeric_pid}/stat").read_text(encoding="ascii").split()
                    )
                except (OSError, ValueError):
                    return False
                if len(fields) <= 2:
                    return False
                return fields[2] not in {"Z", "z", "X", "x"}

            def group_has_live_process():
                try:
                    entries = os.listdir("/proc")
                except OSError:
                    return leader_alive()
                examined = 0
                for entry in entries:
                    if not entry.isdigit():
                        continue
                    examined += 1
                    if examined >= 4096:
                        break
                    try:
                        stat_text = PathLib(f"/proc/{entry}/stat").read_text(encoding="ascii")
                        fields = stat_text.rsplit(")", 1)[1].split()
                    except (OSError, ValueError, IndexError):
                        continue
                    if len(fields) < 3:
                        continue
                    if fields[0] in {"Z", "z", "X", "x"}:
                        continue
                    if fields[2] == str(numeric_pgid):
                        return True
                return False
            terminated = not leader_alive()
            grace_deadline = time.monotonic() + 3.0
            while leader_alive() and time.monotonic() < grace_deadline:
                time.sleep(0.1)
            if leader_alive():
                try:
                    os.killpg(numeric_pgid, signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    pass
                kill_deadline = time.monotonic() + 0.5
                while leader_alive() and time.monotonic() < kill_deadline:
                    time.sleep(0.05)
            terminated = not group_has_live_process()
            record["state"] = "cancelled"
            record["terminated"] = terminated
            write_record(record)
            fcntl.flock(cancel_lock_fd, fcntl.LOCK_UN)
            os.close(cancel_lock_fd)
            print(json.dumps(record))
        else:
            print(json.dumps(record))
    elif operation == "wait":
        deadline = time.monotonic() + min(float(payload.get("timeout", 0)), 60.0)
        record = read_record() if meta_path.is_file() else {"error": "NOT_FOUND"}
        while time.monotonic() < deadline:
            record = read_record() if meta_path.is_file() else {"error": "NOT_FOUND"}
            if record.get("state") in {"succeeded", "failed", "cancelled", "lost", "expired"}:
                break
            time.sleep(0.25)
        print(json.dumps(record))
    else:
        print(json.dumps({"error": "VALIDATION_FAILED"}))
    """
).strip()
_REMOTE_JOB_WORKER = textwrap.dedent(
    """
    import fcntl, json, os, signal, subprocess, tempfile
    from datetime import datetime, timezone
    from pathlib import Path
    meta_path = Path(os.environ["MIKRUS_REMOTE_JOB_META"])
    job_dir = meta_path.parent
    lock_path = meta_path.with_name(meta_path.name + ".lock")
    payload = None
    def acquire_lock():
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | nofollow, 0o600)
        os.fchmod(lock_fd, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        return lock_fd
    def release_lock(lock_fd):
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
    def read_record():
        return json.loads(meta_path.read_text(encoding="utf-8"))
    def write_record(value):
        fd, name = tempfile.mkstemp(prefix=".record.", dir=job_dir)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(value, stream, ensure_ascii=False)
                stream.flush(); os.fsync(stream.fileno())
            os.replace(name, meta_path)
        finally:
            if os.path.exists(name): os.unlink(name)
    def start_ticks(pid):
        try:
            fields = Path(f"/proc/{pid}/stat").read_text(encoding="ascii").split()
            return fields[21]
        except (OSError, IndexError, ValueError):
            return None
    lock_fd = acquire_lock()
    try:
        record = read_record()
        if record.get("state") != "queued":
            raise SystemExit(0)
        payload = record["payload"]
    finally:
        release_lock(lock_fd)
    record.pop("payload", None)
    record["state"] = "running"
    with (job_dir / "stdout").open("wb") as stdout, (job_dir / "stderr").open("wb") as stderr:
        child = subprocess.Popen(
            [payload["executable"], *payload["argv"]],
            cwd=payload.get("cwd"),
            stdin=subprocess.PIPE,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )
        lock_fd = acquire_lock()
        try:
            record = read_record()
            if record.get("state") == "cancelled":
                try:
                    os.killpg(os.getpgid(child.pid), signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    pass
                raise SystemExit(0)
            record["state"] = "running"
            record["startedAt"] = datetime.now(timezone.utc).isoformat()
            record["runtimeIdentity"] = {
                "pid": str(child.pid),
                "pgid": str(os.getpgid(child.pid)),
                "startTicks": start_ticks(child.pid),
            }
            record.pop("payload", None)
            write_record(record)
        finally:
            release_lock(lock_fd)
        worker_failed = False
        try:
            child.communicate(
                input=payload["stdin"].encode()
                if payload.get("stdin") is not None
                else None
            )
        except Exception:
            worker_failed = True
            try:
                os.killpg(os.getpgid(child.pid), signal.SIGKILL)
            except OSError:
                pass
            try:
                child.wait()
            except OSError:
                pass
        code = child.returncode
    lock_fd = acquire_lock()
    try:
        record = read_record()
        if record.get("state") != "cancelled":
            if worker_failed or code != 0:
                record["state"] = "failed"
            else:
                record["state"] = "succeeded"
            if code is not None:
                record["exitCode"] = code
        record.pop("payload", None)
        write_record(record)
    finally:
        release_lock(lock_fd)
    """
).strip()


_FILE_PATCH_HELPER = textwrap.dedent(
    """
    import base64, errno, fcntl, hashlib, json, os, re, stat, sys
    payload = json.load(sys.stdin)
    LIMIT_NEW = 100000
    LIMIT_EXISTING = 1048576
    def fail(code, **extra):
        print(json.dumps({"error": code, **extra}))
        raise SystemExit(0)
    def open_host_lock(name, exclusive, error_code):
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        dir_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | no_follow
        try:
            home_fd = os.open(os.path.expanduser("~"), dir_flags)
        except OSError:
            fail(error_code)
        try:
            try:
                os.mkdir(".mikrus-mcp", 0o700, dir_fd=home_fd)
            except FileExistsError:
                pass
            try:
                state_fd = os.open(".mikrus-mcp", dir_flags, dir_fd=home_fd)
            except OSError:
                fail(error_code)
            try:
                try:
                    os.mkdir("locks", 0o700, dir_fd=state_fd)
                except FileExistsError:
                    pass
                try:
                    locks_fd = os.open("locks", dir_flags, dir_fd=state_fd)
                except OSError:
                    fail(error_code)
                try:
                    fd = os.open(name, os.O_RDWR | os.O_CREAT | no_follow, 0o600, dir_fd=locks_fd)
                except OSError:
                    fail(error_code)
                finally:
                    os.close(locks_fd)
            finally:
                os.close(state_fd)
        finally:
            os.close(home_fd)
        try:
            os.fchmod(fd, 0o600)
            metadata = os.fstat(fd)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
                os.close(fd)
                fail(error_code)
        except OSError:
            fail(error_code)
        fcntl.flock(fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        return fd
    path = payload.get("path")
    expected = payload.get("expected_digest")
    encoded = payload.get("content_b64")
    roots = ("/home", "/opt", "/srv", "/tmp", "/var/log", "/var/www")
    if not isinstance(path, str) or not path.startswith("/") or path == "/":
        fail("VALIDATION_FAILED")
    parts = [part for part in path.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        fail("VALIDATION_FAILED")
    if not isinstance(expected, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", expected):
        fail("VALIDATION_FAILED")
    if not isinstance(encoded, str):
        fail("VALIDATION_FAILED")
    try:
        new_bytes = base64.b64decode(encoded, validate=True)
    except Exception:
        fail("VALIDATION_FAILED")
    if len(new_bytes) > LIMIT_NEW:
        fail("SIZE_LIMIT_EXCEEDED")
    if not any(path == root or path.startswith(root + "/") for root in roots):
        fail("VALIDATION_FAILED")
    cas_lock_fd = open_host_lock("cas.lock", True, "SYMLINK_REJECTED")
    *directories, leaf = parts
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | no_follow
    opened = []
    parent_fd = None
    temporary = None
    replaced = False
    try:
        try:
            parent_fd = os.open("/", directory_flags)
            opened.append(parent_fd)
            for component in directories:
                child = os.open(component, directory_flags, dir_fd=parent_fd)
                opened.append(child)
                parent_fd = child
        except FileNotFoundError:
            fail("NOT_FOUND")
        except NotADirectoryError:
            fail("NOT_FOUND")
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                fail("SYMLINK_REJECTED")
            if exc.errno in (errno.EACCES, errno.EPERM):
                fail("PERMISSION_DENIED")
            fail("WRITE_FAILED")
        try:
            file_fd = os.open(leaf, os.O_RDONLY | no_follow, dir_fd=parent_fd)
        except FileNotFoundError:
            fail("NOT_FOUND")
        except IsADirectoryError:
            fail("NOT_REGULAR_FILE")
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                fail("SYMLINK_REJECTED")
            if exc.errno in (errno.EACCES, errno.EPERM):
                fail("PERMISSION_DENIED")
            fail("WRITE_FAILED")
        opened.append(file_fd)
        try:
            metadata = os.fstat(file_fd)
            if not stat.S_ISREG(metadata.st_mode):
                fail("NOT_REGULAR_FILE")
            if metadata.st_size > LIMIT_EXISTING:
                fail("SIZE_LIMIT_EXCEEDED")
            chunks = []
            remaining = LIMIT_EXISTING
            while remaining > 0:
                chunk = os.read(file_fd, min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            current = b"".join(chunks)
        finally:
            os.close(file_fd)
            opened.pop()
        before_digest = "sha256:" + hashlib.sha256(current).hexdigest()
        if before_digest != expected:
            fail("CONFLICT", before_digest=before_digest, before_size=len(current))
        after_digest = "sha256:" + hashlib.sha256(new_bytes).hexdigest()
        temporary = f".{leaf}.mcp-cas.{os.getpid()}.{os.urandom(8).hex()}"
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | no_follow,
                0o600,
                dir_fd=parent_fd,
            )
            try:
                view = memoryview(new_bytes)
                written = 0
                while written < len(view):
                    written += os.write(descriptor, view[written:])
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.replace(temporary, leaf, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
            replaced = True
            temporary = None
            os.fsync(parent_fd)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EPERM, errno.EDQUOT, errno.ENOSPC):
                code = (
                    "PERMISSION_DENIED"
                    if exc.errno in (errno.EACCES, errno.EPERM)
                    else "WRITE_FAILED"
                )
                fail(code)
            fail("WRITE_FAILED")
        print(json.dumps({
            "status": "REPLACED",
            "before_digest": before_digest,
            "after_digest": after_digest,
            "before_size": len(current),
            "after_size": len(new_bytes),
        }))
        raise SystemExit(0)
    finally:
        if temporary is not None and not replaced:
            try:
                if parent_fd is not None:
                    os.unlink(temporary, dir_fd=parent_fd)
            except OSError:
                pass
        for descriptor in reversed(opened):
            os.close(descriptor)
        fcntl.flock(cas_lock_fd, fcntl.LOCK_UN)
        os.close(cas_lock_fd)
    """
).strip()
_CRON_HELPER = textwrap.dedent(
    """
    import fcntl, hashlib, json, os, re, stat, subprocess, sys
    payload = json.load(sys.stdin)
    LIMIT_TEXT = 1048576
    def fail(code, **extra):
        print(json.dumps({"error": code, **extra}))
        raise SystemExit(0)
    def open_host_lock(name, exclusive, error_code):
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        dir_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | no_follow
        try:
            home_fd = os.open(os.path.expanduser("~"), dir_flags)
        except OSError:
            fail(error_code)
        try:
            try:
                os.mkdir(".mikrus-mcp", 0o700, dir_fd=home_fd)
            except FileExistsError:
                pass
            try:
                state_fd = os.open(".mikrus-mcp", dir_flags, dir_fd=home_fd)
            except OSError:
                fail(error_code)
            try:
                try:
                    os.mkdir("locks", 0o700, dir_fd=state_fd)
                except FileExistsError:
                    pass
                try:
                    locks_fd = os.open("locks", dir_flags, dir_fd=state_fd)
                except OSError:
                    fail(error_code)
                try:
                    fd = os.open(name, os.O_RDWR | os.O_CREAT | no_follow, 0o600, dir_fd=locks_fd)
                except OSError:
                    fail(error_code)
                finally:
                    os.close(locks_fd)
            finally:
                os.close(state_fd)
        finally:
            os.close(home_fd)
        try:
            os.fchmod(fd, 0o600)
            metadata = os.fstat(fd)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
                os.close(fd)
                fail(error_code)
        except OSError:
            fail(error_code)
        fcntl.flock(fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        return fd
    def read_crontab():
        try:
            result = subprocess.run(["crontab", "-l"], capture_output=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace").strip().lower()
            if "no crontab" in detail:
                return ""
            return None
        if len(result.stdout) > LIMIT_TEXT:
            return None
        try:
            return result.stdout.decode("utf-8")
        except UnicodeDecodeError:
            return None
    def digest(text):
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
    def crontab_lock(exclusive):
        code = "CRONTAB_INSTALL_FAILED" if exclusive else "CRONTAB_READ_FAILED"
        return open_host_lock("crontab.lock", exclusive, code)
    operation = payload.get("operation")
    if operation == "read":
        lock_fd = crontab_lock(False)
        try:
            text = read_crontab()
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
        if text is None:
            fail("CRONTAB_READ_FAILED")
        print(json.dumps({"text": text, "hash": digest(text), "size": len(text.encode("utf-8"))}))
        raise SystemExit(0)
    if operation == "install":
        expected_hash = payload.get("expected_hash")
        new_text = payload.get("new_text")
        if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            fail("VALIDATION_FAILED")
        if not isinstance(new_text, str) or "\\x00" in new_text:
            fail("VALIDATION_FAILED")
        if len(new_text.encode("utf-8")) > LIMIT_TEXT:
            fail("VALIDATION_FAILED")
        lock_fd = crontab_lock(True)
        try:
            current = read_crontab()
            if current is None:
                fail("CRONTAB_READ_FAILED")
            if digest(current) != expected_hash:
                fail("CONCURRENT_MODIFICATION")
            try:
                installed = subprocess.run(
                    ["crontab", "-"],
                    input=new_text.encode("utf-8"),
                    capture_output=True,
                    timeout=20,
                )
            except (OSError, subprocess.TimeoutExpired):
                fail("CRONTAB_INSTALL_FAILED")
            if installed.returncode != 0:
                fail("CRONTAB_INSTALL_FAILED")
            fresh = read_crontab()
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
        if fresh is None or digest(fresh) != digest(new_text):
            fail("AMBIGUOUS_OUTCOME")
        print(json.dumps({
            "status": "INSTALLED",
            "hash": digest(new_text),
            "size": len(new_text.encode("utf-8")),
        }))
        raise SystemExit(0)
    fail("VALIDATION_FAILED")
    """
).strip()


_DOCKER_HELPER = textwrap.dedent(
    """
    import json, re, subprocess, sys, time
    payload = json.load(sys.stdin)
    LIMIT_OUTPUT = 1048576
    MAX_IDS = 8
    MAX_FILES = 8
    ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    IMAGE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./:@-]{0,253}$")
    def fail(code, **extra):
        print(json.dumps({"error": code, **extra}))
        raise SystemExit(0)
    def capture(argv, timeout):
        try:
            result = subprocess.run(argv, capture_output=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if len(result.stdout) > LIMIT_OUTPUT or len(result.stderr) > 65536:
            return None
        return result
    def check_text(value, name):
        if not isinstance(value, str) or not ID.fullmatch(value):
            fail("VALIDATION_FAILED")
        return value
    def check_files(files):
        if not isinstance(files, list) or not files or len(files) > MAX_FILES:
            fail("VALIDATION_FAILED")
        for item in files:
            if (
                not isinstance(item, str)
                or not item.startswith("/")
                or ".." in item.split("/")
                or any(character in item for character in "\\x00\\n\\r")
            ):
                fail("VALIDATION_FAILED")
        return files
    def parse_jsonl(raw):
        parsed = []
        for line in raw.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                parsed.append(value)
        return parsed
    operation = payload.get("operation")
    if operation == "ps_filter":
        service = check_text(payload.get("service"), "service")
        argv = ["docker", "ps", "-a", "--filter", f"label=com.docker.compose.service={service}"]
        project = payload.get("project")
        if project is not None:
            checked = check_text(project, "project")
            argv.extend(["--filter", f"label=com.docker.compose.project={checked}"])
        argv.extend(["--format", "json"])
        result = capture(argv, 20)
        if result is None:
            fail("DOCKER_FAILED")
        if result.returncode != 0:
            fail("DOCKER_FAILED", detail=result.stderr.decode("utf-8", errors="replace")[-256:])
        print(json.dumps({"containers": parse_jsonl(result.stdout)}))
        raise SystemExit(0)
    if operation == "inspect":
        identifiers = payload.get("ids")
        if not isinstance(identifiers, list) or not identifiers or len(identifiers) > MAX_IDS:
            fail("VALIDATION_FAILED")
        argv = ["docker", "inspect", "--format", "{{json .}}"]
        for item in identifiers:
            argv.append(check_text(item, "id"))
        result = capture(argv, 20)
        if result is None:
            fail("DOCKER_FAILED")
        containers = parse_jsonl(result.stdout)
        if result.returncode != 0 and not containers:
            fail("NOT_FOUND")
        tail = result.stderr.decode("utf-8", errors="replace")[-256:]
        print(json.dumps({"containers": containers, "stderr_tail": tail}))
        raise SystemExit(0)
    if operation == "compose_config":
        project = check_text(payload.get("project"), "project")
        files = check_files(payload.get("files"))
        argv = ["docker", "compose", "-p", project]
        for item in files:
            argv.extend(["-f", item])
        argv.extend(["config", "--format", "json"])
        result = capture(argv, 25)
        if result is None:
            fail("DOCKER_FAILED")
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace")[-256:]
            fail("COMPOSE_CONFIG_FAILED", detail=detail)
        try:
            parsed = json.loads(result.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            fail("COMPOSE_CONFIG_FAILED")
        print(json.dumps({"config": parsed}))
        raise SystemExit(0)
    if operation == "image_inspect":
        image = payload.get("image")
        if not isinstance(image, str) or not IMAGE.fullmatch(image):
            fail("VALIDATION_FAILED")
        result = capture(["docker", "image", "inspect", "--format", "{{json .}}", image], 20)
        if result is None:
            fail("DOCKER_FAILED")
        parsed = parse_jsonl(result.stdout)
        if result.returncode != 0 or not parsed:
            fail("NOT_FOUND")
        print(json.dumps({"image": parsed[0]}))
        raise SystemExit(0)
    if operation == "compose_up":
        project = check_text(payload.get("project"), "project")
        files = check_files(payload.get("files"))
        service = check_text(payload.get("service"), "service")
        argv = ["docker", "compose", "-p", project]
        for item in files:
            argv.extend(["-f", item])
        argv.extend(["up", "-d", "--no-deps", "--force-recreate", service])
        result = capture(argv, 60)
        if result is None:
            fail("DOCKER_FAILED")
        if result.returncode != 0:
            fail("RECREATE_FAILED", detail=result.stderr.decode("utf-8", errors="replace")[-256:])
        tail = result.stdout.decode("utf-8", errors="replace")[-256:]
        print(json.dumps({"status": "APPLIED", "stdout_tail": tail}))
        raise SystemExit(0)
    if operation == "wait":
        identifier = check_text(payload.get("container_id"), "container_id")
        readiness = payload.get("readiness")
        if readiness not in ("running", "healthy"):
            fail("VALIDATION_FAILED")
        try:
            deadline_seconds = float(payload.get("timeout_seconds"))
        except (TypeError, ValueError):
            fail("VALIDATION_FAILED")
        if not 0.0 <= deadline_seconds <= 25.0:
            fail("VALIDATION_FAILED")
        deadline = time.monotonic() + deadline_seconds
        last_state = None
        last_health = None
        has_health_field = False
        inspected_once = False
        while True:
            result = capture(["docker", "inspect", "--format", "{{json .}}", identifier], 10)
            if result is not None and result.returncode == 0:
                parsed = parse_jsonl(result.stdout)
                if parsed:
                    state = parsed[0].get("State") or {}
                    health = state.get("Health") if isinstance(state.get("Health"), dict) else None
                    last_state = str(state.get("Status") or "")
                    if health is not None:
                        has_health_field = True
                        last_health = str(health.get("Status") or "")
            if not inspected_once:
                inspected_once = True
                first_read = result is not None and result.returncode == 0 and parsed
                if readiness == "healthy" and first_read and not has_health_field:
                    fail("UNSUPPORTED_CONFIGURATION")
            if time.monotonic() >= deadline:
                break
            if readiness == "running" and last_state == "running":
                break
            if readiness == "healthy" and last_health == "healthy":
                break
            time.sleep(1.0)
        if readiness == "healthy" and not has_health_field:
            fail("UNSUPPORTED_CONFIGURATION")
        if readiness == "healthy" and last_health == "unhealthy":
            fail("HEALTH_FAILED", state=last_state, health=last_health)
        if (readiness == "running" and last_state == "running") or (
            readiness == "healthy" and last_health == "healthy"
        ):
            print(json.dumps({"status": "READY", "state": last_state, "health": last_health}))
            raise SystemExit(0)
        fail("READINESS_TIMEOUT", state=last_state, health=last_health)
    fail("VALIDATION_FAILED")
    """
).strip()


class SshClient:
    """AsyncSSH adapter which verifies host identity and bounds process output."""

    def __init__(self, config: TargetConfig) -> None:
        if config.type != "ssh" or config.host is None:
            raise ValueError("SshClient requires an SSH target configuration")
        self.config = config
        self.stable_identity = config.stable_identity
        self._connection: Any = None

    def __repr__(self) -> str:
        return f"SshClient(identity={self.stable_identity!r}, connected={self.is_connected})"

    @property
    def is_connected(self) -> bool:
        return self._connection is not None and not self._connection.is_closed()

    async def open(self) -> None:
        if self._connection is not None and not self._connection.is_closed():
            return
        if self._connection is not None:
            self._connection = None
        import asyncssh

        options: dict[str, Any] = {
            "host": self.config.host,
            "port": self.config.port,
            "username": self.config.user,
            "connect_timeout": self.config.connect_timeout_seconds,
            "login_timeout": self.config.connect_timeout_seconds,
        }
        if self.config.ssh_key:
            if self.config.ssh_cert:
                options["client_keys"] = [(str(self.config.ssh_key), str(self.config.ssh_cert))]
            else:
                options["client_keys"] = [str(self.config.ssh_key)]
        elif self.config.password:
            options["password"] = self.config.password
        if self.config.verify_host_key:
            if self.config.known_hosts_file:
                options["known_hosts"] = asyncssh.read_known_hosts(
                    str(self.config.known_hosts_file)
                )
        else:
            options["known_hosts"] = None
        connection = await asyncssh.connect(**options)
        try:
            if self.config.verify_host_key:
                host_key = connection.get_server_host_key()
                if host_key is None:
                    raise AppError(
                        ErrorCode.AUTHORIZATION,
                        "SSH server did not expose the verified host key",
                    )
                fingerprint = host_key.get_fingerprint("sha256")
                if not isinstance(fingerprint, str) or not fingerprint.startswith("SHA256:"):
                    raise AppError(
                        ErrorCode.AUTHORIZATION,
                        "SSH server host-key fingerprint is unavailable",
                    )
                self.stable_identity = f"{self.config.stable_identity}#host-key={fingerprint}"
            else:
                self.stable_identity = f"{self.config.stable_identity}#host-key=UNVERIFIED"
        except Exception:
            connection.close()
            wait_closed = getattr(connection, "wait_closed", None)
            if wait_closed is not None:
                await wait_closed()
            raise
        self._connection = connection

    async def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            wait_closed = getattr(self._connection, "wait_closed", None)
            if wait_closed is not None:
                await wait_closed()
            self._connection = None

    @staticmethod
    @staticmethod
    async def _terminate_process(process: Any, *, deadline: float | None = None) -> None:
        """Terminate and escalate without exceeding the caller's deadline budget."""
        loop = asyncio.get_running_loop()

        def wait_budget() -> float:
            wait = SSH_TERMINATE_WAIT_SECONDS
            if deadline is not None:
                wait = min(wait, max(0.0, deadline - loop.time()))
            return wait

        terminate = getattr(process, "terminate", None)
        if callable(terminate):
            try:
                terminate()
            except Exception as exc:
                logger.warning("SSH process terminate failed: %s", type(exc).__name__)
        first_wait = wait_budget()
        if first_wait > 0:
            try:
                await asyncio.wait_for(process.wait(), first_wait)
                return
            except asyncio.CancelledError:
                raise
            except (TimeoutError, OSError) as exc:
                if not isinstance(exc, TimeoutError):
                    logger.warning("SSH process wait failed: %s", type(exc).__name__)

        close = getattr(process, "close", None)
        if callable(close):
            try:
                close()
            except Exception as exc:
                logger.warning("SSH process close failed: %s", type(exc).__name__)
        second_wait = wait_budget()
        if second_wait > 0:
            try:
                await asyncio.wait_for(process.wait(), second_wait)
            except asyncio.CancelledError:
                raise
            except (TimeoutError, OSError):
                logger.warning("SSH process channel did not close cleanly")

    async def _run(
        self, command: str, *, timeout: float | None = None, mutation: bool = False
    ) -> dict[str, Any]:
        if self._connection is None:
            raise AppError(ErrorCode.UNAVAILABLE, "SSH client is not open")
        limit = MAX_PROCESS_OUTPUT_BYTES
        process = await self._connection.create_process(command, encoding=None)
        total = 0
        total_lock = asyncio.Lock()

        async def collect(stream: Any) -> bytes:
            nonlocal total
            chunks: list[bytes] = []
            while True:
                chunk = await stream.read(65_536)
                if not chunk:
                    return b"".join(chunks)
                if isinstance(chunk, str):
                    encoded = chunk.encode("utf-8", errors="replace")
                else:
                    encoded = bytes(chunk)
                async with total_lock:
                    total += len(encoded)
                    if total > limit:
                        raise AppError(ErrorCode.UPSTREAM, "SSH output exceeds size limit")
                chunks.append(encoded)

        seconds = float(timeout or self.config.connect_timeout_seconds or SSH_DEFAULT_TIMEOUT)
        try:
            async with asyncio.timeout(seconds):
                stdout, stderr = await asyncio.gather(
                    collect(process.stdout), collect(process.stderr)
                )
                await process.wait()
        except TimeoutError as exc:
            await self._terminate_process(process)
            code = ErrorCode.AMBIGUOUS if mutation else ErrorCode.TIMEOUT
            message = (
                "SSH mutation outcome is unknown after timeout; reconcile target state before retry"
                if mutation
                else f"SSH command exceeded {seconds:g} seconds"
            )
            raise AppError(code, message, retryable=False) from exc
        except asyncio.CancelledError:
            await self._terminate_process(process)
            raise
        except AppError:
            await self._terminate_process(process)
            raise
        return {
            "output": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "exit_code": int(process.exit_status),
        }

    async def _run_sudo(self, command: str, *, timeout: float | None = None) -> dict[str, Any]:
        if not self.config.sudo_password:
            return await self._run(command, timeout=timeout)
        if self._connection is None:
            raise AppError(ErrorCode.UNAVAILABLE, "SSH client is not open")
        process = await self._connection.create_process(
            f"sudo -S -- sh -c {shlex.quote(command)}", encoding=None
        )
        process.stdin.write((self.config.sudo_password + "\n").encode("utf-8"))
        await process.stdin.drain()
        process.stdin.write_eof()
        total = 0
        lock = asyncio.Lock()

        async def collect(stream: Any) -> bytes:
            nonlocal total
            chunks: list[bytes] = []
            while True:
                chunk = await stream.read(65_536)
                if not chunk:
                    return b"".join(chunks)
                data = chunk.encode() if isinstance(chunk, str) else bytes(chunk)
                async with lock:
                    total += len(data)
                    if total > MAX_PROCESS_OUTPUT_BYTES:
                        raise AppError(ErrorCode.UPSTREAM, "SSH output exceeds size limit")
                chunks.append(data)

        seconds = float(timeout or self.config.connect_timeout_seconds)
        try:
            async with asyncio.timeout(seconds):
                stdout, stderr = await asyncio.gather(
                    collect(process.stdout), collect(process.stderr)
                )
                await process.wait()
        except TimeoutError as exc:
            await self._terminate_process(process)
            raise AppError(ErrorCode.TIMEOUT, "sudo command deadline exceeded") from exc
        except asyncio.CancelledError:
            await self._terminate_process(process)
            raise
        except AppError:
            await self._terminate_process(process)
            raise
        return {
            "output": stdout.decode(errors="replace"),
            "stderr": stderr.decode(errors="replace"),
            "exit_code": int(process.exit_status),
        }

    async def execute_program(
        self,
        executable: str,
        argv: list[str],
        cwd: str | None = None,
        stdin: str | None = None,
    ) -> Any:
        """Run a typed program request through a fixed remote helper.

        AsyncSSH's exec API accepts a command string, not a separate argv list
        or native remote cwd. Keep that command constant and pass all
        user-controlled values as JSON to the helper, which applies cwd and
        invokes subprocess with shell=False.

        User-controlled values are JSON input, never part of the remote command
        string. The helper invokes subprocess with shell=False.
        """
        if self._connection is None:
            raise AppError(ErrorCode.UNAVAILABLE, "SSH client is not open")
        process = await self._connection.create_process(
            "python3 -c " + shlex.quote(_PROGRAM_HELPER), encoding=None
        )
        payload = json.dumps(
            {"executable": executable, "argv": argv, "cwd": cwd, "stdin": stdin},
            ensure_ascii=False,
        ).encode("utf-8")
        process.stdin.write(payload)
        await process.stdin.drain()
        process.stdin.write_eof()
        return await self._collect_process(process, timeout=EXEC_HTTP_TIMEOUT, mutation=True)

    async def _remote_job_call(
        self, payload: dict[str, object], *, mutation: bool
    ) -> dict[str, Any]:
        if self._connection is None:
            raise AppError(ErrorCode.UNAVAILABLE, "SSH client is not open")
        process = await self._connection.create_process(
            "python3 -c " + shlex.quote(_REMOTE_JOB_HELPER), encoding=None
        )
        process.stdin.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        await process.stdin.drain()
        process.stdin.write_eof()
        result = await self._collect_process(process, timeout=EXEC_HTTP_TIMEOUT, mutation=mutation)
        parsed = result
        if not isinstance(parsed, dict):
            raise AppError(ErrorCode.UPSTREAM_PROTOCOL, "remote job helper returned invalid data")
        if parsed.get("error") == "NOT_FOUND":
            raise AppError(ErrorCode.NOT_FOUND, "remote job not found")
        if parsed.get("error") == "IDEMPOTENCY_CONFLICT":
            raise AppError(ErrorCode.CONFLICT, "remote job idempotency key is already bound")
        if parsed.get("error") == "CONFLICT":
            raise AppError(ErrorCode.CONFLICT, "remote job process identity changed")
        if parsed.get("error") == "VALIDATION_FAILED":
            raise AppError(ErrorCode.VALIDATION, "remote job request is invalid")
        parsed.pop("payload", None)
        return parsed

    async def remote_job_start(
        self,
        *,
        job_id: str,
        request_digest: str,
        executable: str,
        argv: list[str],
        cwd: str | None,
        stdin: str | None,
    ) -> dict[str, Any]:
        return await self._remote_job_call(
            {
                "operation": "start",
                "job_id": job_id,
                "request_digest": request_digest,
                "executable": executable,
                "argv": argv,
                "cwd": cwd,
                "stdin": stdin,
                "worker": _REMOTE_JOB_WORKER,
            },
            mutation=True,
        )

    async def remote_job_status(self, *, job_id: str) -> dict[str, Any]:
        return await self._remote_job_call(
            {"operation": "status", "job_id": job_id}, mutation=False
        )

    async def remote_job_wait(self, *, job_id: str, timeout_seconds: float) -> dict[str, Any]:
        return await self._remote_job_call(
            {"operation": "wait", "job_id": job_id, "timeout": timeout_seconds}, mutation=False
        )

    async def remote_job_result(self, *, job_id: str) -> dict[str, Any]:
        return await self._remote_job_call(
            {"operation": "result", "job_id": job_id}, mutation=False
        )

    async def remote_job_output(
        self, *, job_id: str, stream: str, offset: int, max_bytes: int
    ) -> dict[str, Any]:
        return await self._remote_job_call(
            {
                "operation": "output",
                "job_id": job_id,
                "stream": stream,
                "offset": offset,
                "max_bytes": max_bytes,
            },
            mutation=False,
        )

    async def remote_job_cancel(self, *, job_id: str, reason: str) -> dict[str, Any]:
        return await self._remote_job_call(
            {"operation": "cancel", "job_id": job_id, "reason": reason}, mutation=True
        )

    async def _json_stdin_call(
        self,
        helper: str,
        payload: dict[str, object],
        *,
        mutation: bool,
        errors: dict[str, tuple[ErrorCode, str]],
    ) -> dict[str, Any]:
        """Run one fixed helper with all request values on its JSON stdin.

        The remote command is constant (`python3 -c <helper>`); error labels are
        translated to application error messages by the caller-provided map.
        """
        if self._connection is None:
            raise AppError(ErrorCode.UNAVAILABLE, "SSH client is not open")
        process = await self._connection.create_process(
            "python3 -c " + shlex.quote(helper), encoding=None
        )
        process.stdin.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        await process.stdin.drain()
        process.stdin.write_eof()
        result = await self._collect_process(process, timeout=EXEC_HTTP_TIMEOUT, mutation=mutation)
        error = result.get("error")
        if isinstance(error, str) and error in errors:
            raise AppError(*errors[error])
        return result

    async def file_patch_atomic(
        self, *, path: str, expected_digest: str, content_b64: str
    ) -> dict[str, Any]:
        """Compare-and-swap replace of one regular file through a fixed helper.

        The helper reads the current bytes and writes the replacement while
        anchored to a single no-follow directory traversal, so the CAS
        precondition and the rename cannot race a re-opened path (no TOCTOU).
        """
        return await self._json_stdin_call(
            _FILE_PATCH_HELPER,
            {
                "path": path,
                "expected_digest": expected_digest,
                "content_b64": content_b64,
            },
            mutation=True,
            errors={
                "CONFLICT": (
                    ErrorCode.CONFLICT,
                    "file patch CAS precondition failed; current file digest differs (CONFLICT)",
                ),
                "NOT_FOUND": (
                    ErrorCode.NOT_FOUND,
                    "file patch target or parent path does not exist (NOT_FOUND)",
                ),
                "SYMLINK_REJECTED": (
                    ErrorCode.VALIDATION,
                    "file patch path contains a symlink component (SYMLINK_REJECTED)",
                ),
                "NOT_REGULAR_FILE": (
                    ErrorCode.VALIDATION,
                    "file patch target is not a regular file (NOT_REGULAR_FILE)",
                ),
                "SIZE_LIMIT_EXCEEDED": (
                    ErrorCode.VALIDATION,
                    "file patch content exceeds the size limit (SIZE_LIMIT_EXCEEDED)",
                ),
                "PERMISSION_DENIED": (
                    ErrorCode.UPSTREAM,
                    "remote file system denied the patch operation (PERMISSION_DENIED)",
                ),
                "WRITE_FAILED": (
                    ErrorCode.UPSTREAM,
                    "remote file patch write failed (WRITE_FAILED)",
                ),
                "VALIDATION_FAILED": (
                    ErrorCode.VALIDATION,
                    "remote helper rejected the file patch request",
                ),
            },
        )

    async def cron_read(self) -> dict[str, Any]:
        """Read the installed crontab through typed argv with bounded output."""
        return await self._json_stdin_call(
            _CRON_HELPER,
            {"operation": "read"},
            mutation=False,
            errors={
                "CRONTAB_READ_FAILED": (
                    ErrorCode.UPSTREAM,
                    "the installed crontab could not be read (CRONTAB_READ_FAILED)",
                ),
                "VALIDATION_FAILED": (
                    ErrorCode.VALIDATION,
                    "remote helper rejected the crontab read request",
                ),
            },
        )

    async def cron_install(self, *, expected_hash: str, new_text: str) -> dict[str, Any]:
        """Install new crontab text only when the fresh pre-install read matches."""
        return await self._json_stdin_call(
            _CRON_HELPER,
            {"operation": "install", "expected_hash": expected_hash, "new_text": new_text},
            mutation=True,
            errors={
                "CONCURRENT_MODIFICATION": (
                    ErrorCode.CONFLICT,
                    "the installed crontab changed concurrently (CONCURRENT_MODIFICATION)",
                ),
                "CRONTAB_READ_FAILED": (
                    ErrorCode.UPSTREAM,
                    "the installed crontab could not be read (CRONTAB_READ_FAILED)",
                ),
                "CRONTAB_INSTALL_FAILED": (
                    ErrorCode.UPSTREAM,
                    "the crontab install command failed (CRONTAB_INSTALL_FAILED)",
                ),
                "AMBIGUOUS_OUTCOME": (
                    ErrorCode.AMBIGUOUS,
                    "the crontab install could not be verified after install (AMBIGUOUS_OUTCOME)",
                ),
                "VALIDATION_FAILED": (
                    ErrorCode.VALIDATION,
                    "remote helper rejected the crontab install request",
                ),
            },
        )

    async def docker_ps_filter(self, *, service: str, project: str | None = None) -> dict[str, Any]:
        payload: dict[str, object] = {"operation": "ps_filter", "service": service}
        if project is not None:
            payload["project"] = project
        return await self._json_stdin_call(
            _DOCKER_HELPER,
            payload,
            mutation=False,
            errors={
                "DOCKER_FAILED": (
                    ErrorCode.UPSTREAM,
                    "the docker CLI invocation failed (DOCKER_FAILED)",
                ),
                "VALIDATION_FAILED": (
                    ErrorCode.VALIDATION,
                    "remote helper rejected the docker request",
                ),
            },
        )

    async def docker_inspect(self, ids: list[str]) -> dict[str, Any]:
        return await self._json_stdin_call(
            _DOCKER_HELPER,
            {"operation": "inspect", "ids": ids},
            mutation=False,
            errors={
                "NOT_FOUND": (
                    ErrorCode.NOT_FOUND,
                    "docker container not found (NOT_FOUND)",
                ),
                "DOCKER_FAILED": (
                    ErrorCode.UPSTREAM,
                    "the docker CLI invocation failed (DOCKER_FAILED)",
                ),
                "VALIDATION_FAILED": (
                    ErrorCode.VALIDATION,
                    "remote helper rejected the docker request",
                ),
            },
        )

    async def docker_compose_config(self, *, project: str, files: list[str]) -> dict[str, Any]:
        return await self._json_stdin_call(
            _DOCKER_HELPER,
            {"operation": "compose_config", "project": project, "files": files},
            mutation=False,
            errors={
                "COMPOSE_CONFIG_FAILED": (
                    ErrorCode.UPSTREAM,
                    "the compose configuration could not be resolved (COMPOSE_CONFIG_FAILED)",
                ),
                "DOCKER_FAILED": (
                    ErrorCode.UPSTREAM,
                    "the docker CLI invocation failed (DOCKER_FAILED)",
                ),
                "VALIDATION_FAILED": (
                    ErrorCode.VALIDATION,
                    "remote helper rejected the docker request",
                ),
            },
        )

    async def docker_image_inspect(self, image: str) -> dict[str, Any]:
        return await self._json_stdin_call(
            _DOCKER_HELPER,
            {"operation": "image_inspect", "image": image},
            mutation=False,
            errors={
                "NOT_FOUND": (
                    ErrorCode.NOT_FOUND,
                    "docker image not found (NOT_FOUND)",
                ),
                "DOCKER_FAILED": (
                    ErrorCode.UPSTREAM,
                    "the docker CLI invocation failed (DOCKER_FAILED)",
                ),
                "VALIDATION_FAILED": (
                    ErrorCode.VALIDATION,
                    "remote helper rejected the docker request",
                ),
            },
        )

    async def docker_compose_up(
        self, *, project: str, files: list[str], service: str
    ) -> dict[str, Any]:
        return await self._json_stdin_call(
            _DOCKER_HELPER,
            {"operation": "compose_up", "project": project, "files": files, "service": service},
            mutation=True,
            errors={
                "RECREATE_FAILED": (
                    ErrorCode.UPSTREAM,
                    "the compose recreate failed (RECREATE_FAILED)",
                ),
                "DOCKER_FAILED": (
                    ErrorCode.UPSTREAM,
                    "the docker CLI invocation failed (DOCKER_FAILED)",
                ),
                "VALIDATION_FAILED": (
                    ErrorCode.VALIDATION,
                    "remote helper rejected the docker request",
                ),
            },
        )

    async def docker_service_wait(
        self, *, container_id: str, readiness: str, timeout_seconds: float
    ) -> dict[str, Any]:
        return await self._json_stdin_call(
            _DOCKER_HELPER,
            {
                "operation": "wait",
                "container_id": container_id,
                "readiness": readiness,
                "timeout_seconds": timeout_seconds,
            },
            mutation=False,
            errors={
                "READINESS_TIMEOUT": (
                    ErrorCode.TIMEOUT,
                    "the service did not reach the requested readiness in time (READINESS_TIMEOUT)",
                ),
                "HEALTH_FAILED": (
                    ErrorCode.UPSTREAM,
                    "the service health check is unhealthy (HEALTH_FAILED)",
                ),
                "UNSUPPORTED_CONFIGURATION": (
                    ErrorCode.VALIDATION,
                    "the container defines no health check (UNSUPPORTED_CONFIGURATION)",
                ),
                "DOCKER_FAILED": (
                    ErrorCode.UPSTREAM,
                    "the docker CLI invocation failed (DOCKER_FAILED)",
                ),
                "VALIDATION_FAILED": (
                    ErrorCode.VALIDATION,
                    "remote helper rejected the docker request",
                ),
            },
        )

    async def _collect_process(
        self, process: Any, *, timeout: float, mutation: bool
    ) -> dict[str, Any]:
        total = 0
        total_lock = asyncio.Lock()

        async def collect(stream: Any) -> bytes:
            nonlocal total
            chunks: list[bytes] = []
            while True:
                chunk = await stream.read(65_536)
                if not chunk:
                    return b"".join(chunks)
                data = (
                    chunk.encode("utf-8", errors="replace")
                    if isinstance(chunk, str)
                    else bytes(chunk)
                )
                async with total_lock:
                    total += len(data)
                    if total > MAX_PROCESS_OUTPUT_BYTES:
                        raise AppError(ErrorCode.UPSTREAM, "SSH output exceeds size limit")
                chunks.append(data)

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        try:
            async with asyncio.timeout(max(0.0, timeout - 2 * SSH_TERMINATE_WAIT_SECONDS)):
                stdout, stderr = await asyncio.gather(
                    collect(process.stdout), collect(process.stderr)
                )
                await process.wait()
        except TimeoutError as exc:
            await self._terminate_process(process, deadline=deadline)
            code = ErrorCode.AMBIGUOUS if mutation else ErrorCode.TIMEOUT
            raise AppError(code, "SSH program outcome is unknown after timeout") from exc
        except asyncio.CancelledError:
            await self._terminate_process(process, deadline=deadline)
            raise
        except AppError:
            await self._terminate_process(process, deadline=deadline)
            raise
        try:
            result = json.loads(stdout.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            stderr_tail = stderr.decode("utf-8", errors="replace")[-256:]
            raise AppError(
                ErrorCode.UPSTREAM_PROTOCOL,
                f"SSH program helper returned invalid JSON: {stderr_tail}",
            ) from exc
        if not isinstance(result, dict):
            raise AppError(ErrorCode.UPSTREAM_PROTOCOL, "SSH program helper returned invalid data")
        return result

    async def read_file(self, path: str) -> Any:
        return await self._run(
            _remote_read_prefix(path)
            + 'file -b --mime-encoding "$resolved" | grep -q binary && '
            + "echo 'ERROR: binary file' || head -n 200 -- \"$resolved\""
        )

    async def write_file(self, path: str, content: str) -> Any:
        command = _remote_atomic_write_command(path, content)
        return await self._run(command, timeout=EXEC_HTTP_TIMEOUT, mutation=True)

    async def get_service_status(self, name: str) -> Any:
        return await self._run(
            f"systemctl status --no-pager -- {shlex.quote(validate_service_name(name))}"
        )

    async def change_service_state(self, name: str, action: str) -> Any:
        action = validate_service_action(action)
        if action in {"status", "is-active", "is-enabled"}:
            raise ValidationError("read-only service actions use get_service_status")
        return await self._run(
            f"systemctl {action} -- {shlex.quote(validate_service_name(name))}", mutation=True
        )

    async def analyze_disk(self, path: str = "/") -> Any:
        result = await self._run(
            _remote_read_prefix(path)
            + 'df -h -- "$resolved"; echo ---TOP20---; '
            + 'du -sh -- "$resolved"/* 2>/dev/null | sort -rh | head -n 20',
            timeout=30,
        )
        if result.get("exit_code", 0) != 0:
            stderr = result.get("stderr", "")
            detail = stderr or result.get("output", "")
            raise AppError(
                ErrorCode.UPSTREAM,
                f"disk analysis failed with exit code {result['exit_code']}: {detail}",
            )
        return result

    async def check_port(self, port: str) -> Any:
        value = validate_port(port)
        return await self._run(
            f"ss -tlnp 2>/dev/null | grep -F ':{value} ' || echo PORT_NOT_LISTENING"
        )

    async def list_processes(self) -> Any:
        return await self._run("ps aux --sort=-%mem | head -n 20")

    async def terminate_process(self, target: str) -> Any:
        value = shlex.quote(validate_process_target(target))
        if target.isdigit():
            return await self._run(f"kill -TERM -- {value}", mutation=True)
        return await self._run(f"pkill -TERM -x -- {value}", mutation=True)

    async def update_system(self) -> Any:
        return await self._run(
            "export DEBIAN_FRONTEND=noninteractive; apt-get update; "
            "apt-get upgrade -y -o Dpkg::Options::=--force-confdef "
            "-o Dpkg::Options::=--force-confold",
            timeout=120,
            mutation=True,
        )

    async def list_directory(self, path: str) -> Any:
        return await self._run(_remote_read_prefix(path) + 'ls -la -- "$resolved"')

    async def tail_file(self, path: str, lines: int = 50) -> Any:
        count = validate_lines_param(lines)
        return await self._run(_remote_read_prefix(path) + f'tail -n {count} -- "$resolved"')

    async def search_in_files(self, path: str, pattern: str) -> Any:
        term = shlex.quote(validate_search_pattern(pattern))
        return await self._run(
            _remote_read_prefix(path)
            + f'grep -r -F -n --max-count={MAX_SEARCH_RESULTS} -- {term} "$resolved" '
            + f"2>/dev/null | head -n {MAX_SEARCH_RESULTS}",
            timeout=30,
        )

    async def get_memory_info(self) -> Any:
        return await self._run("free -h")

    async def get_network_info(self) -> Any:
        return await self._run("ip addr; echo ---PORTS---; ss -tlnp")

    async def get_process_tree(self) -> Any:
        return await self._run("ps auxf | head -n 100")

    async def list_docker_containers(self) -> Any:
        return MikrusClient._parse_docker_jsonl(
            await self._run("docker ps -a --format '{{json .}}'")
        )

    async def get_docker_logs(self, container: str, lines: int = 50) -> Any:
        return await self._run(
            f"docker logs --tail {validate_lines_param(lines)} -- "
            f"{shlex.quote(validate_container_name(container))}"
        )

    async def get_docker_stats(self) -> Any:
        return MikrusClient._parse_docker_jsonl(
            await self._run("docker stats --no-stream --format '{{json .}}'")
        )

    async def get_journal_logs(self, unit: str, lines: int = 50) -> Any:
        return await self._run_sudo(
            f"journalctl -u {shlex.quote(validate_service_name(unit))} "
            f"-n {validate_lines_param(lines, MAX_JOURNAL_LINES)} -q --no-pager"
        )

    async def find_system_errors(self, hours: int = 1) -> Any:
        return await self._run_sudo(
            f"journalctl -p err --since '{validate_hours_param(hours)} hours ago' "
            f"-q --no-pager -n {MAX_JOURNAL_LINES}"
        )

    async def search_journal_logs(self, term: str, lines: int = 50) -> Any:
        return await self._run_sudo(
            f"journalctl -q --no-pager -n 5000 | grep -i -F -- "
            f"{shlex.quote(validate_search_pattern(term))} | "
            f"tail -n {validate_lines_param(lines, MAX_JOURNAL_LINES)}"
        )
