#!/usr/bin/env python3
"""Issue one short-lived approval into an owner-only local registry file."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mikrus_mcp.approvals import ApprovalRegistry, normalized_arguments_digest  # noqa: E402
from mikrus_mcp.config import Settings, load_settings  # noqa: E402
from mikrus_mcp.targets import TargetRegistry  # noqa: E402


def _initialize(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        return
    try:
        os.write(descriptor, b'{"tokens": {}}\n')
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--file", required=True, type=Path)
    value.add_argument("--capability", required=True)
    value.add_argument("--principal", required=True)
    value.add_argument(
        "--server",
        required=True,
        help=(
            "Configured server alias. SSH approvals resolve the currently verified "
            "host-key fingerprint before the approval is persisted."
        ),
    )
    value.add_argument("--resource", required=True)
    value.add_argument(
        "--arguments-json",
        required=True,
        help="Canonical post-validation operation arguments as a JSON object; omit server",
    )
    value.add_argument("--ttl-seconds", type=float, default=60.0)
    return value


async def _resolved_target_identity(settings: Settings, server: str) -> str:
    targets = settings.targets
    try:
        target = targets[server]
    except KeyError as exc:
        raise SystemExit(f"unknown configured server: {server}") from exc
    if target.type != "ssh":
        return target.stable_identity
    registry = TargetRegistry(dict(targets))
    try:
        client = await registry.get(server)
        return client.stable_identity
    finally:
        await registry.close()


def main() -> int:
    args = parser().parse_args()
    try:
        operation_arguments = json.loads(args.arguments_json)
    except json.JSONDecodeError as exc:
        raise SystemExit("--arguments-json must be valid JSON") from exc
    if not isinstance(operation_arguments, dict):
        raise SystemExit("--arguments-json must encode a JSON object")
    if "server" in operation_arguments:
        raise SystemExit("--arguments-json must omit server; target identity is bound separately")
    arguments_digest = normalized_arguments_digest(operation_arguments)

    settings = load_settings()
    target_identity = asyncio.run(_resolved_target_identity(settings, args.server))

    path = args.file.absolute()
    _initialize(path)
    metadata = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        raise SystemExit("approval file must be a regular non-symlink file")
    registry = ApprovalRegistry.from_file(path)
    registry.issue(
        args.capability,
        args.principal,
        target_identity,
        args.resource,
        arguments_digest,
        ttl_seconds=args.ttl_seconds,
    )
    print(
        json.dumps(
            {
                "capability": args.capability,
                "principal": args.principal,
                "server": args.server,
                "target_identity": target_identity,
                "resource": args.resource,
                "arguments_digest": arguments_digest,
                "ttl_seconds": args.ttl_seconds,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
