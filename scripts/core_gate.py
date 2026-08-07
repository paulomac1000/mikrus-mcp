#!/usr/bin/env python3
"""Run deterministic credential-free checks available in every development environment."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*arguments: str) -> None:
    subprocess.run(arguments, cwd=ROOT, check=True)


def main() -> int:
    run(sys.executable, "-m", "compileall", "-q", "src", "tests", "scripts")
    run(sys.executable, "scripts/check_docs.py")
    run(sys.executable, "scripts/check_workflows.py")
    run(
        sys.executable,
        "-m",
        "pytest",
        "tests/unit",
        "tests/smoke",
        "--collect-only",
        "-q",
    )
    run(sys.executable, "-m", "pytest", "tests/unit", "tests/smoke", "-q")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
