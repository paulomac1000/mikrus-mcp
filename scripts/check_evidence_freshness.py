#!/usr/bin/env python3
"""Fail closed when AI Skills evidence is stale relative to the reviewed code revision."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
DEFAULT_ALLOWED_EVIDENCE_PATHS = frozenset(
    {
        "atomic-claims.yaml",
        "migration-assessment.yaml",
        "docs/ai-skills-review.md",
        "docs/compliance-status.md",
    }
)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _load(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a YAML object")
    return value


def _revision(document: dict[str, Any], path: Path) -> str:
    repository = document.get("repository")
    if not isinstance(repository, dict):
        raise ValueError(f"{path.name}: repository must be an object")
    revision = repository.get("revision")
    if not isinstance(revision, str) or FULL_SHA.fullmatch(revision) is None:
        raise ValueError(f"{path.name}: repository.revision must be a full lowercase SHA")
    return revision


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-evidence-path",
        action="append",
        default=[],
        help="Additional repository-relative path allowed after the assessed revision.",
    )
    args = parser.parse_args()

    assessment_path = ROOT / "migration-assessment.yaml"
    atomic_path = ROOT / "atomic-claims.yaml"
    assessment_revision = _revision(_load(assessment_path), assessment_path)
    atomic_revision = _revision(_load(atomic_path), atomic_path)
    if assessment_revision != atomic_revision:
        raise SystemExit(
            "migration-assessment.yaml and atomic-claims.yaml must bind the same revision"
        )

    head = _git("rev-parse", "HEAD")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", assessment_revision, head],
        cwd=ROOT,
        check=False,
    )
    if ancestor.returncode != 0:
        raise SystemExit(
            f"assessed revision {assessment_revision} is not an ancestor of HEAD {head}"
        )

    allowed = set(DEFAULT_ALLOWED_EVIDENCE_PATHS)
    allowed.update(args.allow_evidence_path)
    changed = {
        line
        for line in _git("diff", "--name-only", f"{assessment_revision}..{head}").splitlines()
        if line
    }
    unexpected = sorted(changed - allowed)
    if unexpected:
        raise SystemExit(
            "AI Skills evidence is stale: non-evidence files changed after the assessed revision: "
            + ", ".join(unexpected)
        )

    print(
        f"AI Skills evidence is bound to {assessment_revision}; "
        f"HEAD {head} differs only by {len(changed)} allowed evidence file(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
