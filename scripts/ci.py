#!/usr/bin/env python3
"""Run the complete local quality gate after installing the development environment."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*arguments: str) -> None:
    subprocess.run(arguments, cwd=ROOT, check=True)


def main() -> int:
    run(sys.executable, "scripts/core_gate.py")
    run(sys.executable, "-m", "ruff", "check", "src", "tests", "scripts")
    run(sys.executable, "-m", "ruff", "format", "--check", "src", "tests", "scripts")
    run(sys.executable, "-m", "mypy", "src/mikrus_mcp", "scripts")
    run(sys.executable, "-m", "bandit", "-q", "-lll", "-iii", "-r", "src/mikrus_mcp")
    run(sys.executable, "-m", "pip_audit", "--local", "--progress-spinner", "off")
    run(
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--cov=mikrus_mcp",
        "--cov-branch",
        "--cov-report=term-missing",
        "--cov-report=xml",
        "--cov-fail-under=85",
        "--junitxml=repository-junit.xml",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
