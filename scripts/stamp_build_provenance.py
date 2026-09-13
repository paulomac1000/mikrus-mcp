#!/usr/bin/env python3
"""Generate the immutable build provenance record embedded in mikrus-mcp."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mikrus_mcp import __version__  # noqa: E402
from mikrus_mcp.provenance import package_content_digest, policy_revision  # noqa: E402

_SOURCE_REVISION_RE = re.compile(r"[0-9a-f]{40}")


def source_revision(value: str) -> str:
    candidate = value.strip().lower()
    if _SOURCE_REVISION_RE.fullmatch(candidate) is None:
        raise argparse.ArgumentTypeError(
            "source revision must be exactly 40 hexadecimal characters"
        )
    return candidate


def build_id(value: str) -> str:
    candidate = value.strip()
    if not candidate or len(candidate) > 200:
        raise argparse.ArgumentTypeError("build id must contain 1..200 characters")
    return candidate


def config_revision(value: str) -> str:
    candidate = value.strip()
    if not candidate or len(candidate) > 256:
        raise argparse.ArgumentTypeError("config revision must contain 1..256 characters")
    return candidate


def built_at(value: str) -> str:
    candidate = value.strip()
    parse_value = candidate[:-1] + "+00:00" if candidate.endswith("Z") else candidate
    try:
        parsed = datetime.fromisoformat(parse_value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("built-at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("built-at must include a timezone offset")
    return parsed.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--source-revision", required=True, type=source_revision)
    value.add_argument("--build-id", required=True, type=build_id)
    value.add_argument("--built-at", type=built_at)
    value.add_argument("--config-revision", default="unknown", type=config_revision)
    value.add_argument("--package-dir", type=Path, default=ROOT / "src" / "mikrus_mcp")
    return value


def main() -> int:
    args = parser().parse_args()
    package_dir = args.package_dir.resolve(strict=True)
    if not package_dir.is_dir():
        raise SystemExit(f"package directory is not a directory: {package_dir}")
    timestamp = (
        args.built_at
        if args.built_at is not None
        else datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )
    record: dict[str, object] = {
        "schemaVersion": 1,
        "serviceVersion": __version__,
        "sourceRevision": args.source_revision,
        "buildId": args.build_id,
        "builtAt": timestamp,
        "policyRevision": policy_revision(package_dir),
        "packageContentDigest": package_content_digest(package_dir),
        "configRevision": args.config_revision,
    }
    output = package_dir / "_build_provenance.json"
    if output.is_symlink():
        raise SystemExit(f"refusing to replace symlinked provenance record: {output}")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=package_dir,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(record, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    print(
        "Stamped build provenance: "
        f"sourceRevision={record['sourceRevision']} "
        f"buildId={record['buildId']} "
        f"packageContentDigest={record['packageContentDigest']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
