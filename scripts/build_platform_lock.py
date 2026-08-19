#!/usr/bin/env python3
"""Render a platform-exact hash lock from one already resolved wheelhouse."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from packaging.utils import canonicalize_name, parse_wheel_filename


def render_lock(wheelhouse: Path, *, python_version: str, source: str) -> str:
    records: dict[str, tuple[str, str, str]] = {}
    for wheel in sorted(wheelhouse.glob("*.whl")):
        name, version, _build, _tags = parse_wheel_filename(wheel.name)
        canonical = canonicalize_name(name)
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
        record = (str(name), str(version), digest)
        if canonical in records and records[canonical] != record:
            raise ValueError(f"multiple artifacts selected for {canonical}")
        records[canonical] = record
    if not records:
        raise ValueError("wheelhouse contains no wheels")
    lines = [
        "# Platform-exact dependency lock.",
        f"# Generated from {source} on Linux x64 / CPython {python_version}.",
        "# Exactly one verified wheel artifact is allowed per distribution.",
        "",
    ]
    for canonical_key in sorted(records):
        display_name, display_version, digest = records[canonical_key]
        lines.append(f"{display_name}=={display_version} --hash=sha256:{digest}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheelhouse", required=True, type=Path)
    parser.add_argument("--python-version", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.write_text(
        render_lock(
            args.wheelhouse,
            python_version=args.python_version,
            source=args.source,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
