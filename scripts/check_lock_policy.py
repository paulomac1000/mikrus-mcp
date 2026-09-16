#!/usr/bin/env python3
"""Validate committed dependency-lock policy deterministically without network I/O.

Candidate verification answers one question: can this exact candidate be
installed and validated from the committed platform-exact hash locks?  A fresh
re-resolution against mutable public package state is a dependency *refresh*
event (see ``.github/workflows/dependency-refresh.yml``), never a
verdict-bearing candidate check.

This script performs bounded, network-free consistency checks:

1. every supported platform/runtime tuple has committed runtime and dev locks;
2. committed locks are regular files whose package entries carry hash pins;
3. the pip toolchain version declared in the dev locks, in the CI workflows,
   and in the documented local bootstrap commands is one canonical value;
4. dependency re-resolution is confined to the canonical refresh lane.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

WORKFLOW_DIR = Path(".github") / "workflows"
DOC_INSTALL_PATTERN = re.compile(r'pip[=!]=\s*"?([0-9][0-9a-zA-Z.\-]*[^"\s])"?')
PIP_LINE = re.compile(r"^pip==([0-9][0-9a-zA-Z.\-]*)\s")
CANONICAL_PIP_VERSION = "26.2.1"
SUPPORTED_PYTHON_VARIANTS = ("312", "313", "314")
LOCK_KINDS = ("runtime", "dev")
DOC_FILES = ("AGENTS.md", "README.md")
REFRESH_WORKFLOW = "dependency-refresh.yml"
RESOLUTION_TRIGGERS = ("pip-compile", "piptools")


def _lock_path(root: Path, kind: str, variant: str) -> Path:
    return root / f"requirements-{kind}-linux-x64-py{variant}.lock"


def _iter_pip_versions(text: str) -> list[str]:
    return [
        match.group(1) for match in (PIP_LINE.match(line) for line in text.splitlines()) if match
    ]


def _check_locks(root: Path) -> list[str]:
    findings: list[str] = []
    for variant in SUPPORTED_PYTHON_VARIANTS:
        for kind in LOCK_KINDS:
            path = _lock_path(root, kind, variant)
            if not path.is_file() or path.is_symlink():
                findings.append(f"missing or non-regular committed lock: {path.name}")
                continue
            package_lines = 0
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                package_lines += 1
                if "--hash=sha256:" not in stripped:
                    findings.append(
                        f"{path.name}: unpinned package entry: {stripped.split('==', 1)[0]}"
                    )
            if package_lines == 0:
                findings.append(f"{path.name}: contains no package entries")
    return findings


def _check_toolchain_consistency(root: Path) -> list[str]:
    findings: list[str] = []
    for variant in SUPPORTED_PYTHON_VARIANTS:
        path = _lock_path(root, "dev", variant)
        if not path.is_file() or path.is_symlink():
            continue
        versions = _iter_pip_versions(path.read_text(encoding="utf-8"))
        if len(versions) != 1 or versions[0] != CANONICAL_PIP_VERSION:
            findings.append(
                f"{path.name}: pip toolchain {versions or ['<missing>']} does not match "
                f"canonical {CANONICAL_PIP_VERSION}"
            )
    for name in DOC_FILES:
        doc = root / name
        if not doc.is_file():
            findings.append(f"missing documented bootstrap file: {name}")
            continue
        found = {
            match.group(1)
            for match in DOC_INSTALL_PATTERN.finditer(doc.read_text(encoding="utf-8"))
            if match.group(1).startswith("26.")
        }
        stale = {version for version in found if version != CANONICAL_PIP_VERSION}
        if stale:
            findings.append(
                f"{name}: documented pip toolchain {sorted(stale)} does not match canonical "
                f"{CANONICAL_PIP_VERSION}"
            )
    return findings


def _check_workflow_pip(root: Path) -> list[str]:
    findings: list[str] = []
    refresh_seen = False
    for path in sorted((root / WORKFLOW_DIR).glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        declared = re.findall(r'PIP_VERSION:\s*"?([0-9][0-9a-zA-Z.\-]*)"?', text)
        if declared and any(version != CANONICAL_PIP_VERSION for version in declared):
            findings.append(
                f"{path.name}: PIP_VERSION {declared} does not match "
                f"canonical {CANONICAL_PIP_VERSION}"
            )
        if any(trigger in text for trigger in RESOLUTION_TRIGGERS):
            if path.name != REFRESH_WORKFLOW:
                findings.append(
                    f"{path.name}: dependency re-resolution is restricted to {REFRESH_WORKFLOW}"
                )
            else:
                refresh_seen = True
    if not refresh_seen:
        findings.append(f"{REFRESH_WORKFLOW}: canonical dependency refresh lane is missing")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root
    findings = [
        *_check_locks(root),
        *_check_toolchain_consistency(root),
        *_check_workflow_pip(root),
    ]
    if findings:
        for finding in findings:
            print(f"ERROR: {finding}", file=sys.stderr)
        return 1
    print(
        "lock policy: PASS (committed locks consistent; candidate verification is "
        "lock-install-only; re-resolution confined to the refresh lane)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
