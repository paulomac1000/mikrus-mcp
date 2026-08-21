#!/usr/bin/env python3
"""Fail closed when AI Skills evidence is stale relative to the reviewed code revision.

The assessed revision is declared by ``assessed_revision`` in the
``docs/compliance-status.md`` frontmatter. Content identity is enforced by an
evidence-only delta rather than commit ancestry, so squash merges are supported:
after a squash the bound revision may leave the merged history, and the evidence
must then be rebound to the merged commit.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
BINDING_DOCUMENT = Path("docs/compliance-status.md")
DEFAULT_ALLOWED_EVIDENCE_PATHS = frozenset(
    {
        "docs/compliance-status.md",
        "docs/ai-skills-review.md",
        "CHANGELOG.md",
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


def _assessed_revision() -> str:
    text = BINDING_DOCUMENT.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise SystemExit(f"{BINDING_DOCUMENT} must start with YAML frontmatter")
    closing = text.index("\n---\n", 4)
    document = yaml.safe_load(text[4:closing])
    if not isinstance(document, dict):
        raise SystemExit(f"{BINDING_DOCUMENT} frontmatter must be a mapping")
    revision = document.get("assessed_revision")
    if not isinstance(revision, str) or FULL_SHA.fullmatch(revision) is None:
        raise SystemExit(
            f"{BINDING_DOCUMENT} must declare assessed_revision as a full 40-character SHA"
        )
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

    assessment_revision = _assessed_revision()
    head = _git("rev-parse", "HEAD")
    present = subprocess.run(
        ["git", "cat-file", "-e", f"{assessment_revision}^{{commit}}"],
        cwd=ROOT,
        check=False,
    )
    if present.returncode != 0:
        raise SystemExit(
            f"assessed revision {assessment_revision} is not present in this checkout. "
            "This is expected after a squash merge: update assessed_revision in "
            f"{BINDING_DOCUMENT} to the merged commit and commit the change as "
            "evidence-only."
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
