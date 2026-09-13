#!/usr/bin/env python3
"""Build the project wheel with an explicit build-provenance mode.

``--provenance unstamped`` removes any embedded build stamp so the wheel is
built from unstamped sources. ``--provenance stamped`` requires the stamp to be
newer than every tracked source file, closing the stale-stamp trap where a
wheel is rebuilt from changed sources but keeps an outdated embedded identity.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAMP = ROOT / "src" / "mikrus_mcp" / "_build_provenance.json"


def source_paths() -> list[Path]:
    paths = [ROOT / "pyproject.toml"]
    paths.extend(sorted((ROOT / "src").rglob("*.py")))
    paths.extend(sorted((ROOT / "src").rglob("*.json")))
    return [path for path in paths if path.is_file() and path != STAMP]


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument(
        "--provenance",
        choices=("unstamped", "stamped"),
        required=True,
        help="unstamped removes the build stamp; stamped requires a fresh stamp",
    )
    value.add_argument(
        "--out",
        type=Path,
        default=ROOT / "dist",
        help="wheel output directory (default: ./dist)",
    )
    return value


def main() -> int:
    args = parser().parse_args()
    if args.provenance == "unstamped":
        STAMP.unlink(missing_ok=True)
    else:
        if not STAMP.is_file():
            raise SystemExit(
                "stamped build requires src/mikrus_mcp/_build_provenance.json; "
                "run scripts/stamp_build_provenance.py first"
            )
        stamp_mtime = STAMP.stat().st_mtime
        stale = [path for path in source_paths() if path.stat().st_mtime > stamp_mtime]
        if stale:
            names = ", ".join(str(path.relative_to(ROOT)) for path in stale[:5])
            raise SystemExit(
                "stamped build refused: sources are newer than the build stamp "
                f"(re-stamp before building): {names}"
            )
    args.out.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(args.out)],
        cwd=ROOT,
        check=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
