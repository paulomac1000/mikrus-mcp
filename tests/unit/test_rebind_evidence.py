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
def evidence_repo(tmp_path: Path) -> tuple[Path, str, str]:  # noqa: RET504
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
    binding_commit = _git(root, "rev-parse", "HEAD")
    (root / "src.txt").write_text("implementation drift", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "implementation commit after assessment")
    second = _git(root, "rev-parse", "HEAD")
    return root, binding_commit, second


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
    root, binding_commit, second = evidence_repo
    del second
    _git(root, "checkout", "-q", binding_commit)
    assert _run(root, "--revision", binding_commit, "--verify-only") == 0
    assert "evidence binding verified" in capsys.readouterr().out


def test_verify_only_rejects_candidate_drift(evidence_repo: tuple[Path, str, str]) -> None:
    root, _binding_commit, second = evidence_repo
    before = (root / BINDING_RELATIVE).read_text(encoding="utf-8")
    with pytest.raises(SystemExit):
        _run(root, "--revision", second, "--verify-only")
    assert (root / BINDING_RELATIVE).read_text(encoding="utf-8") == before


def test_verify_only_accepts_evidence_only_drift(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    (root / "src.txt").write_text("implementation", encoding="utf-8")
    (root / BINDING_RELATIVE).write_text(
        "---\nassessed_revision: " + "1" * 40 + "\n---\nbody\n", encoding="utf-8"
    )
    git = shutil.which("git") or "git"
    subprocess.run([git, "init", "-q"], cwd=root, check=True)  # noqa: S603
    subprocess.run(  # noqa: S603
        [git, "config", "user.email", "t@example.com"], cwd=root, check=True
    )
    subprocess.run([git, "config", "user.name", "t"], cwd=root, check=True)  # noqa: S603
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "implementation")
    implementation = _git(root, "rev-parse", "HEAD")
    binding = root / BINDING_RELATIVE
    binding.write_text(
        binding.read_text(encoding="utf-8").replace("1" * 40, implementation),
        encoding="utf-8",
    )
    (root / "CHANGELOG.md").write_text("## evidence-only entry\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "evidence-only rebind")
    evidence_commit = _git(root, "rev-parse", "HEAD")
    assert _run(root, "--revision", evidence_commit, "--verify-only") == 0


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


def test_default_rebind_rejects_dirty_working_tree(
    evidence_repo: tuple[Path, str, str],
) -> None:
    import sys

    root, _first, second = evidence_repo
    (root / "service.py").write_text("uncommitted source change", encoding="utf-8")
    argv = sys.argv
    sys.argv = ["rebind_evidence.py", "--repo", str(root)]
    try:
        with pytest.raises(SystemExit):
            rebind_main()
    finally:
        sys.argv = argv
    assert f"assessed_revision: {second}" not in (root / BINDING_RELATIVE).read_text(
        encoding="utf-8"
    )


def test_rebind_rejects_revision_that_is_not_head(
    evidence_repo: tuple[Path, str, str],
) -> None:
    root, first, second = evidence_repo
    before = (root / BINDING_RELATIVE).read_text(encoding="utf-8")
    with pytest.raises(SystemExit):
        _run(root, "--revision", first)
    assert (root / BINDING_RELATIVE).read_text(encoding="utf-8") == before
    del second


def test_verify_only_reads_binding_from_the_revision_not_working_tree(
    evidence_repo: tuple[Path, str, str],
) -> None:
    root, binding_commit, second = evidence_repo
    del second
    _git(root, "checkout", "-q", binding_commit)
    binding = root / BINDING_RELATIVE
    binding.write_text(
        binding.read_text(encoding="utf-8").replace(
            f"assessed_revision: {binding_commit}", "assessed_revision: " + "9" * 40
        ),
        encoding="utf-8",
    )
    assert _run(root, "--revision", binding_commit, "--verify-only") == 0


def test_verify_only_rejects_duplicate_assessed_revision(
    evidence_repo: tuple[Path, str, str],
) -> None:
    root, binding_commit, second = evidence_repo
    binding = root / BINDING_RELATIVE
    current = binding_commit[: len(binding_commit)]  # revision recorded in the doc
    doc_text = binding.read_text(encoding="utf-8")
    current_line = [
        line
        for line in doc_text.splitlines()
        if line.startswith("assessed_revision: ") and line != ""
    ][0]
    current = current_line.split(":", 1)[1].strip()
    text = doc_text.replace(
        f"assessed_revision: {current}",
        f"assessed_revision: {binding_commit}\nassessed_revision: " + "2" * 40,
    )
    binding.write_text(text, encoding="utf-8")
    staged = subprocess.run(
        [shutil.which("git") or "git", "add", "."],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert staged.returncode == 0, staged.stderr
    result = subprocess.run(
        [shutil.which("git") or "git", "commit", "-qm", "conflicting duplicate binding"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    head_sha = _git(root, "rev-parse", "HEAD")
    assert head_sha != "HEAD"
    with pytest.raises(SystemExit) as duplicate_error:
        _run(root, "--revision", head_sha, "--verify-only")
    assert "exactly one assessed_revision" in str(duplicate_error.value)
    del second
