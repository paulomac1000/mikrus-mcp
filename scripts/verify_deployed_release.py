#!/usr/bin/env python3
"""Verify a deployment receipt against the immutable installed build identity."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mikrus_mcp.provenance import capture_runtime_provenance


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument(
        "--receipt",
        type=Path,
        help="deployment receipt JSON; otherwise MIKRUS_MCP_DEPLOYMENT_RECEIPT_FILE is used",
    )
    return value


def main() -> int:
    args = parser().parse_args()
    snapshot = capture_runtime_provenance(receipt_path=args.receipt)
    print(json.dumps(snapshot.as_dict(), indent=2, sort_keys=True))
    if snapshot.deployment.binding == "verified" and snapshot.package_integrity == "verified":
        return 0
    if snapshot.deployment.binding == "missing":
        return 2
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
