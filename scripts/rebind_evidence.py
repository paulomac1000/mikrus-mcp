#!/usr/bin/env python3
"""Bind AI Skills evidence to the exact acceptance candidate SHA.

The canonical rebind step for the governed delivery path. Given an exact
candidate revision, it verifies the candidate is present in the checkout,
optionally verifies that provider CI genuinely executed and succeeded for
that exact SHA, and then atomically rewrites only the ``assessed_revision``
line in the ``docs/compliance-status.md`` frontmatter. It never relabels
stale evidence: binding happens only after the requested checks pass for
the exact candidate.

Modes:
- default: verify + rebind the frontmatter for the candidate;
- ``--verify-only``: read-only check that a revision's evidence binding and
  optional provider run are current; usable by release/integration tooling
  before accepting or publishing a candidate.

Implementation commits between bindings do NOT require this helper; the
freshness gate rejects non-evidence drift after the assessed revision, and
the rebind belongs to the moment a candidate is selected for acceptance.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
BINDING_DOCUMENT = Path("docs") / "compliance-status.md"
ASSESSMENT_LINE = re.compile(r"^assessed_revision: [0-9a-f]{40}$", re.MULTILINE)
ALLOWED_EVIDENCE_PATHS = frozenset(
    {
        "migration-assessment.yaml",
        "docs/compliance-status.md",
        "docs/ai-skills-review.md",
        "CHANGELOG.md",
    }
)


class RebindError(SystemExit):
    def __init__(self, message: str) -> None:
        super().__init__(f"rebind_evidence: {message}")


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RebindError(f"git {' '.join(args[:2])} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _provider_run_ok(root: Path, revision: str) -> None:
    gh = shutil.which("gh")
    if gh is None:
        raise RebindError(
            "TODO(provider): provider verification requested but the GitHub CLI is "
            "unavailable; provider evidence for this SHA must be executed before binding"
        )
    repository = os.environ.get("GITHUB_REPOSITORY")
    if not repository:
        remote = _git(root, "remote", "get-url", "origin")
        match = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?$", remote)
        if match is None:
            raise RebindError("cannot resolve repository identity for provider verification")
        repository = match.group(1)
    result = subprocess.run(
        [
            gh,
            "api",
            "--paginate",
            f"/repos/{repository}/actions/workflows/ci.yml/runs?head_sha={revision}"
            "&status=success&per_page=100",
            "--jq",
            '.workflow_runs | map(select(.head_sha == "' + revision + '")) | length',
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RebindError(
            f"TODO(provider): provider verification query failed: {result.stderr.strip()}"
        )
    runs = int(result.stdout.strip() or "0")
    if runs == 0:
        raise RebindError(
            "TODO(provider): no successful provider CI run exists for exact "
            f"{revision}; evidence cannot be bound without provider execution"
        )


def _assessed_revision(binding_path: Path) -> str:
    text = binding_path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise RebindError(f"{binding_path} must start with YAML frontmatter")
    closing = text.index("\n---\n", 4)
    match = ASSESSMENT_LINE.search(text[4:closing])
    if match is None:
        raise RebindError(
            f"{binding_path} frontmatter must declare assessed_revision as a full SHA"
        )
    return match.group(0).split(":", 1)[1].strip()


def _rewrite_binding(binding_path: Path, revision: str) -> None:
    text = binding_path.read_text(encoding="utf-8")
    closing = text.index("\n---\n", 4)
    frontmatter = text[4:closing]
    updated_frontmatter, count = ASSESSMENT_LINE.subn(f"assessed_revision: {revision}", frontmatter)
    if count != 1:
        raise RebindError("failed to update assessed_revision deterministically")
    updated = text[:4] + updated_frontmatter + text[closing:]
    if updated == text:
        raise RebindError(
            f"assessed_revision is already bound to {revision}; no stale binding to replace"
        )
    handle, temporary = tempfile.mkstemp(prefix=f".{binding_path.name}.", dir=binding_path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(updated)
        os.replace(temporary, binding_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--revision",
        default=None,
        help="Exact candidate SHA (default: current HEAD of the checkout)",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Read-only check that the current binding is an ancestor of HEAD with "
        "only evidence-path drift; no files are modified.",
    )
    parser.add_argument(
        "--require-provider-run",
        action="store_true",
        help="Require a successful provider CI run for the exact candidate before binding.",
    )
    args = parser.parse_args()
    root = args.repo
    binding_path = root / BINDING_DOCUMENT
    if not binding_path.is_file():
        raise RebindError(f"binding document is missing: {BINDING_DOCUMENT}")

    revision = args.revision or _git(root, "rev-parse", "HEAD")
    if FULL_SHA.fullmatch(revision) is None:
        raise RebindError(f"--revision must be a full 40-character SHA: {revision!r}")
    present = subprocess.run(
        ["git", "cat-file", "-e", f"{revision}^{{commit}}"],
        cwd=root,
        check=False,
        capture_output=True,
    )
    if present.returncode != 0:
        raise RebindError(f"candidate revision {revision} is not present in this checkout")

    if args.require_provider_run:
        _provider_run_ok(root, revision)

    if args.verify_only:
        bound = _assessed_revision(binding_path)
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", bound, revision],
            cwd=root,
            check=False,
            capture_output=True,
        )
        if ancestor.returncode != 0:
            raise RebindError(
                f"evidence binding {bound} is not an ancestor of exact candidate "
                f"{revision}; rebind after fresh provider evidence"
            )
        allowed = set(ALLOWED_EVIDENCE_PATHS)
        changed = {
            line
            for line in _git(root, "diff", "--name-only", f"{bound}..{revision}").splitlines()
            if line
        }
        unexpected = sorted(changed - allowed)
        if unexpected:
            raise RebindError(
                "candidate drifted after the assessed revision in non-evidence files: "
                + ", ".join(unexpected)
            )
        print(f"evidence binding verified for exact candidate {revision}")
        return 0

    _rewrite_binding(binding_path, revision)
    print(f"assessed_revision bound to exact candidate {revision}")
    if args.require_provider_run:
        print("provider CI run verified for the exact candidate")
    return 0


if __name__ == "__main__":
    sys.exit(main())
