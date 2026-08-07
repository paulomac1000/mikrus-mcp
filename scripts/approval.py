#!/usr/bin/env python3
"""Issue one short-lived approval into an owner-only local registry file."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mikrus_mcp.approvals import ApprovalRegistry  # noqa: E402


def _initialize(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        return
    try:
        encoded = b'{"tokens": {}}\n'
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--file", required=True, type=Path)
    value.add_argument("--capability", required=True)
    value.add_argument("--principal", required=True)
    value.add_argument("--target", required=True)
    value.add_argument("--resource", required=True)
    value.add_argument("--ttl-seconds", type=float, default=60.0)
    return value


def main() -> int:
    args = parser().parse_args()
    path = args.file.absolute()
    _initialize(path)
    metadata = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        raise SystemExit("approval file must be a regular non-symlink file")
    registry = ApprovalRegistry.from_file(path)
    registry.issue(
        args.capability,
        args.principal,
        args.target,
        args.resource,
        ttl_seconds=args.ttl_seconds,
    )
    print(
        json.dumps(
            {
                "capability": args.capability,
                "principal": args.principal,
                "target": args.target,
                "resource": args.resource,
                "ttl_seconds": args.ttl_seconds,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
