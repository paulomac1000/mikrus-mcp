"""SSH adapter facade with the issue #29 bounded legacy-GC hardening applied."""

from __future__ import annotations

from mikrus_mcp.clients import ssh_impl as _impl
from mikrus_mcp.clients.legacy_gc_patch import patch_remote_job_helper

_impl._REMOTE_JOB_HELPER = patch_remote_job_helper(_impl._REMOTE_JOB_HELPER)

SshClient = _impl.SshClient
_REMOTE_JOB_HELPER = _impl._REMOTE_JOB_HELPER
_REMOTE_JOB_WORKER = _impl._REMOTE_JOB_WORKER
_PROGRAM_HELPER = _impl._PROGRAM_HELPER


def __getattr__(name: str):
    return getattr(_impl, name)


__all__ = ["SshClient"]
