from __future__ import annotations

import shutil
import subprocess  # noqa: S404
from pathlib import Path

import pytest

from scripts.rebind_evidence import main as rebind_main


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603
        [shutil.which("git") or "git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.fixture()
def evidence_repo(tmp_path: Path) -> tuple[Path, str, str]:
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    (root / BINDING_RELATIVE).write_text(
        """---
afds_schema_version: 2
assessed_revision: """
        + "1" * 40
        + """
description: compliance binding
---
# Compliance status

body text that must never be touched by the rebind helper
""",
        encoding="utf-8",
    )
    git = shutil.which("git") or "git"
    subprocess.run([git, "init", "-q"], cwd=root, check=True)  # noqa: S603
    subprocess.run([git, "config", "user.email", "t@example.com"], cwd=root, check=True)  # noqa: S603
    subprocess.run([git, "config", "user.name", "t"], cwd=root, check=True)  # noqa: S603
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "assessed implementation")
    first = _git(root, "rev-parse", "HEAD")
    binding = root / BINDING_RELATIVE
    binding.write_text(
        binding.read_text(encoding="utf-8").replace("1" * 40, first), encoding="utf-8"
    )
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "bind evidence to assessed implementation")
    (root / "src.txt").write_text("implementation drift", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "implementation commit after assessment")
    second = _git(root, "rev-parse", "HEAD")
    return root, first, second


BINDING_RELATIVE = Path("docs") / "compliance-status.md"


def _run(root: Path, *extra: str) -> int:
    import sys

    argv = sys.argv
    sys.argv = ["rebind_evidence.py", "--repo", str(root), *extra]
    try:
        return rebind_main()
    finally:
        sys.argv = argv


def test_rebind_updates_only_assessed_revision_line(
    evidence_repo: tuple[Path, str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    root, first, second = evidence_repo
    before = (root / BINDING_RELATIVE).read_text(encoding="utf-8")
    assert _run(root, "--revision", second) == 0
    assert f"assessed_revision bound to exact candidate {second}" in capsys.readouterr().out
    after = (root / BINDING_RELATIVE).read_text(encoding="utf-8")
    assert f"assessed_revision: {second}" in after
    body_before = before.split("\n---\n", 1)[1]
    body_after = after.split("\n---\n", 1)[1]
    assert body_before == body_after
    assert f"assessed_revision: {'1' * 40}" not in after


def test_rebind_rejects_unknown_revision(evidence_repo: tuple[Path, str, str]) -> None:
    root, _first, _second = evidence_repo
    unknown = "f" * 40
    with pytest.raises(SystemExit):
        _run(root, "--revision", unknown)


def test_rebind_rejects_short_revision(evidence_repo: tuple[Path, str, str]) -> None:
    root, _first, second = evidence_repo
    with pytest.raises(SystemExit):
        _run(root, "--revision", second[:12])


def test_verify_only_accepts_current_exact_binding(
    evidence_repo: tuple[Path, str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    root, first, second = evidence_repo
    del second
    _git(root, "checkout", "-q", "HEAD^")  # tree at the evidence-binding commit
    assert _run(root, "--revision", first, "--verify-only") == 0
    assert "evidence binding verified" in capsys.readouterr().out


def test_verify_only_rejects_candidate_drift_but_accepts_evidence_only_drift(
    evidence_repo: tuple[Path, str, str], tmp_path: Path
) -> None:
    root, first, second = evidence_repo
    before = (root / BINDING_RELATIVE).read_text(encoding="utf-8")
    with pytest.raises(SystemExit):
        _run(root, "--revision", second, "--verify-only")
    assert (root / BINDING_RELATIVE).read_text(encoding="utf-8") == before

    del tmp_path
    _git(root, "checkout", "-qb", "evidence-only")
    (root / "CHANGELOG.md").write_text("## evidence-only entry\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "evidence-only rebind")
    candidate = _git(root, "rev-parse", "HEAD")
    _run(root, "--revision", candidate)
    assert _run(root, "--revision", candidate, "--verify-only") == 0
    del first


def test_provider_run_required_fails_without_gh(
    evidence_repo: tuple[Path, str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _first, second = evidence_repo
    monkeypatch.setattr("scripts.rebind_evidence.shutil.which", lambda name: None)
    before = (root / BINDING_RELATIVE).read_text(encoding="utf-8")
    with pytest.raises(SystemExit):
        _run(root, "--revision", second, "--require-provider-run")
    assert (root / BINDING_RELATIVE).read_text(encoding="utf-8") == before


def test_rebind_is_idempotent_for_current_binding(
    evidence_repo: tuple[Path, str, str],
) -> None:
    root, _first, second = evidence_repo
    assert _run(root, "--revision", second) == 0
    with pytest.raises(SystemExit):
        _run(root, "--revision", second)


def test_allowed_evidence_paths_stay_in_sync_with_freshness_gate() -> None:
    from scripts.check_evidence_freshness import DEFAULT_ALLOWED_EVIDENCE_PATHS
    from scripts.rebind_evidence import ALLOWED_EVIDENCE_PATHS

    assert ALLOWED_EVIDENCE_PATHS == set(DEFAULT_ALLOWED_EVIDENCE_PATHS)
