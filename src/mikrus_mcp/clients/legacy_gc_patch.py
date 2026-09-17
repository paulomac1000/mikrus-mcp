"""Issue #29 residual: hard-bound legacy flat-layout GC enumeration."""

from __future__ import annotations

import textwrap

_HELPER_IMPORT = (
    "import fcntl, hashlib, json, os, re, shutil, signal, stat, subprocess, sys, tempfile, time"
)
_HELPER_IMPORT_WITH_CTYPES = (
    "import ctypes, fcntl, hashlib, json, os, re, shutil, signal, stat, subprocess, sys, tempfile, time"
)
_START = "        # Legacy flat-layout compatibility:"
_END = "    finally:\n        if not existing_bs:"

_NEW_LEGACY_BLOCK = textwrap.indent(
    textwrap.dedent(
        r'''
        # Legacy flat-layout compatibility: jobs created before the trie
        # migration remain directly under <root>/<job_id>. Do not rename
        # them because detached workers may still hold those absolute paths.
        # Sweep the root with a persisted Linux directory cookie instead of
        # materializing/sorting an index. Each invocation consumes at most
        # legacy_raw_budget raw readdir entries, keeps O(1) in-memory state,
        # and resumes without replaying an arbitrarily long prefix. EOF
        # clears the cursor so later rolling-upgrade writes are discovered.
        legacy_cursor_path = root / ".gc-legacy-cursor"
        legacy_lock_path = root / ".gc-legacy-cursor.lock"
        legacy_index_path = root / ".gc-legacy-index"
        legacy_raw_budget = max(64, 4 * budget)
        summary["legacyIterated"] = 0
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        directory_flag = getattr(os, "O_DIRECTORY", 0)

        class _LegacyDirent(ctypes.Structure):
            _fields_ = [
                ("d_ino", ctypes.c_ulong),
                ("d_off", ctypes.c_long),
                ("d_reclen", ctypes.c_ushort),
                ("d_type", ctypes.c_ubyte),
                ("d_name", ctypes.c_char * 256),
            ]

        def _read_legacy_cookie():
            try:
                cursor_fd = os.open(legacy_cursor_path, os.O_RDONLY | nofollow)
                try:
                    raw = os.read(cursor_fd, 257)
                finally:
                    os.close(cursor_fd)
                if len(raw) > 256:
                    return 0
                parsed = json.loads(raw)
                value = parsed.get("o") if isinstance(parsed, dict) else None
                if isinstance(value, int) and 0 <= value <= 0x7FFFFFFFFFFFFFFF:
                    return value
            except (OSError, ValueError):
                pass
            return 0

        def _write_legacy_cookie(value):
            fd, temporary = tempfile.mkstemp(
                prefix=".gc-legacy-cursor.", dir=root
            )
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump({"o": int(value)}, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, legacy_cursor_path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)

        def _clear_legacy_cookie():
            try:
                st = os.lstat(legacy_cursor_path)
            except FileNotFoundError:
                return
            except OSError:
                summary["errors"] += 1
                return
            try:
                if stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode):
                    os.unlink(legacy_cursor_path)
                else:
                    summary["errors"] += 1
            except OSError:
                summary["errors"] += 1

        legacy_lock_fd = None
        try:
            legacy_lock_fd = os.open(
                legacy_lock_path,
                os.O_RDWR | os.O_CREAT | nofollow,
                0o600,
            )
            os.fchmod(legacy_lock_fd, 0o600)
            fcntl.flock(legacy_lock_fd, fcntl.LOCK_EX)

            # The PR #34 migration index is obsolete. It was bounded on read
            # but built with an unbounded scan/sort. Remove only the internal
            # regular file/symlink itself and never follow it.
            try:
                old_index = os.lstat(legacy_index_path)
            except FileNotFoundError:
                old_index = None
            except OSError:
                old_index = None
                summary["errors"] += 1
            if old_index is not None and (
                stat.S_ISREG(old_index.st_mode) or stat.S_ISLNK(old_index.st_mode)
            ):
                try:
                    os.unlink(legacy_index_path)
                except OSError:
                    summary["errors"] += 1

            cookie = _read_legacy_cookie()
            try:
                libc = ctypes.CDLL(None, use_errno=True)
                libc.fdopendir.argtypes = [ctypes.c_int]
                libc.fdopendir.restype = ctypes.c_void_p
                libc.readdir.argtypes = [ctypes.c_void_p]
                libc.readdir.restype = ctypes.POINTER(_LegacyDirent)
                libc.telldir.argtypes = [ctypes.c_void_p]
                libc.telldir.restype = ctypes.c_long
                libc.seekdir.argtypes = [ctypes.c_void_p, ctypes.c_long]
                libc.seekdir.restype = None
                libc.closedir.argtypes = [ctypes.c_void_p]
                libc.closedir.restype = ctypes.c_int
            except (AttributeError, OSError):
                libc = None
                summary["errors"] += 1

            if libc is not None:
                directory_fd = None
                directory_stream = None
                try:
                    directory_fd = os.open(
                        root,
                        os.O_RDONLY | directory_flag | nofollow,
                    )
                    directory_stream = libc.fdopendir(directory_fd)
                    if not directory_stream:
                        os.close(directory_fd)
                        directory_fd = None
                        summary["errors"] += 1
                    else:
                        # fdopendir owns directory_fd after success.
                        directory_fd = None
                        if cookie:
                            libc.seekdir(directory_stream, ctypes.c_long(cookie))
                        eof = False
                        next_cookie = cookie
                        while summary["legacyIterated"] < legacy_raw_budget:
                            ctypes.set_errno(0)
                            entry_ptr = libc.readdir(directory_stream)
                            if not entry_ptr:
                                if ctypes.get_errno() == 0:
                                    eof = True
                                else:
                                    summary["errors"] += 1
                                break
                            summary["legacyIterated"] += 1
                            summary["iterated"] += 1
                            position = int(libc.telldir(directory_stream))
                            if position >= 0:
                                next_cookie = position
                            raw_name = bytes(entry_ptr.contents.d_name).split(b"\x00", 1)[0]
                            name = os.fsdecode(raw_name)
                            if name in {".", ".."} or name.startswith("."):
                                continue
                            target = root / name
                            if JOB_ID.fullmatch(name) is None:
                                try:
                                    target_stat = os.lstat(target)
                                except OSError:
                                    continue
                                if not stat.S_ISDIR(target_stat.st_mode):
                                    evict(root, name)
                                continue
                            summary["visited"] += 1
                            summary["enumerated"] += 1
                            process_managed_job(target)
                        if eof:
                            _clear_legacy_cookie()
                        elif next_cookie >= 0:
                            _write_legacy_cookie(next_cookie)
                except OSError:
                    summary["errors"] += 1
                finally:
                    if directory_stream:
                        libc.closedir(directory_stream)
                    elif directory_fd is not None:
                        os.close(directory_fd)
        except OSError:
            summary["errors"] += 1
        finally:
            if legacy_lock_fd is not None:
                try:
                    fcntl.flock(legacy_lock_fd, fcntl.LOCK_UN)
                finally:
                    os.close(legacy_lock_fd)
        '''
    ).strip("\n")
    + "\n",
    "        ",
)


def patch_remote_job_helper(helper: str) -> str:
    """Patch exactly the #29 legacy-GC residual in the embedded helper.

    The patch fails closed on source drift so the historical unbounded
    index/discovery implementation cannot silently remain active.
    """
    if helper.count(_HELPER_IMPORT) != 1:
        raise RuntimeError("remote-job helper import marker drifted")
    helper = helper.replace(_HELPER_IMPORT, _HELPER_IMPORT_WITH_CTYPES, 1)
    start = helper.find(_START)
    if start < 0:
        raise RuntimeError("legacy GC start marker drifted")
    end = helper.find(_END, start)
    if end < 0:
        raise RuntimeError("legacy GC end marker drifted")
    return helper[:start] + _NEW_LEGACY_BLOCK + helper[end:]
