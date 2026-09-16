from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_lock_policy import main as check_lock_policy_main
from scripts.check_workflows import ROOT, audit


def test_repository_workflows_match_declared_profiles() -> None:
    workflow_dir = ROOT / ".github" / "workflows"
    findings = [finding for path in sorted(workflow_dir.glob("*.yml")) for finding in audit(path)]
    assert findings == []


def test_pull_request_workflow_cannot_use_secrets_or_write_permissions(tmp_path: Path) -> None:
    workflow = tmp_path / "unsafe.yml"
    workflow.write_text(
        """name: unsafe
on:
  pull_request:
permissions:
  contents: write
concurrency:
  group: unsafe
  cancel-in-progress: true
jobs:
  test:
    runs-on: ubuntu-24.04
    timeout-minutes: 5
    steps:
      - run: echo '${{ secrets.TOKEN }}'
""",
        encoding="utf-8",
    )
    findings = audit(workflow)
    assert any("forbidden contents: write" in finding for finding in findings)
    assert any("references secrets" in finding for finding in findings)


def test_sha_only_release_does_not_create_stable_version_tag() -> None:
    workflow = (ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
    assert "release_tag: ${{ steps.revision.outputs.release_tag }}" in workflow
    assert 'echo "release_tag=$release_tag" >> "$GITHUB_OUTPUT"' in workflow
    assert "RELEASE_TAG: ${{ needs.validate-release.outputs.release_tag }}" in workflow
    assert 'if [[ -n "$RELEASE_TAG" ]]; then' in workflow
    assert 'version_ref="$repository:$VERSION"' in workflow


def _write_lock(path: Path, *, pip_version: str | None) -> None:
    lines = ["# Platform-exact dependency lock.", ""]
    if pip_version is not None:
        lines.append(f"pip=={pip_version} --hash=sha256:{'a' * 64}")
    lines.append("somepkg==1.0.0 --hash=sha256:" + "b" * 64)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _lock_policy_tree(tmp_path: Path, *, pip_version: str = "26.2.1") -> Path:
    root = tmp_path / "repo"
    workflow_dir = root / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    for variant in ("312", "313", "314"):
        _write_lock(root / f"requirements-runtime-linux-x64-py{variant}.lock", pip_version=None)
        _write_lock(root / f"requirements-dev-linux-x64-py{variant}.lock", pip_version=pip_version)
    (root / "AGENTS.md").write_text(
        f'.venv/bin/python -m pip install "pip=={pip_version}"\n', encoding="utf-8"
    )
    (root / "README.md").write_text(
        f'.venv/bin/python -m pip install "pip=={pip_version}"\n', encoding="utf-8"
    )
    (workflow_dir / "dependency-refresh.yml").write_text(
        "on:\n  workflow_dispatch:\nsteps:\n  - run: python -m piptools compile\n",
        encoding="utf-8",
    )
    return root


def _run_lock_policy(root: Path) -> int:
    import sys

    argv = sys.argv
    sys.argv = ["check_lock_policy.py", "--root", str(root)]
    try:
        return check_lock_policy_main()
    finally:
        sys.argv = argv


def test_lock_policy_passes_on_consistent_tree(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run_lock_policy(_lock_policy_tree(tmp_path)) == 0
    assert "lock policy: PASS" in capsys.readouterr().out


def test_candidate_workflow_re_resolution_is_restricted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _lock_policy_tree(tmp_path)
    (root / ".github" / "workflows" / "ci.yml").write_text(
        "on:\n  push:\nsteps:\n  - run: python -m piptools compile\n", encoding="utf-8"
    )
    assert _run_lock_policy(root) == 1
    assert "dependency re-resolution is restricted" in capsys.readouterr().err


def test_new_matching_upstream_package_does_not_affect_candidate_lock_policy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A newer upstream package cannot invalidate a committed-lock candidate."""
    root = _lock_policy_tree(tmp_path)
    for variant in ("312", "313", "314"):
        lock = root / f"requirements-runtime-linux-x64-py{variant}.lock"
        lock.write_text(lock.read_text(encoding="utf-8"), encoding="utf-8")
    assert _run_lock_policy(root) == 0


def test_refresh_lane_missing_fails_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _lock_policy_tree(tmp_path)
    (root / ".github" / "workflows" / "dependency-refresh.yml").unlink()
    assert _run_lock_policy(root) == 1
    assert "canonical dependency refresh lane is missing" in capsys.readouterr().err


def test_stale_pip_cache_cannot_enter_policy_result(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Policy result depends only on committed bytes, never on resolver cache state."""
    root = _lock_policy_tree(tmp_path)
    cache = tmp_path / "stale-pip-cache"
    cache.mkdir()
    (cache / "junk.whl").write_bytes(b"not a real wheel")
    assert _run_lock_policy(root) == 0


def test_normal_ci_never_mutates_lock_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "piptools" not in ci and "pip-compile" not in ci
    assert "scripts/build_platform_lock.py" not in ci
    assert "check_lock_policy.py" in ci


def test_refresh_covers_every_supported_variant(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = (ROOT / ".github" / "workflows" / "dependency-refresh.yml").read_text(encoding="utf-8")
    for version in ("3.12", "3.13", "3.14"):
        assert version in text


def test_documented_toolchain_matches_canonical_pip(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _lock_policy_tree(tmp_path, pip_version="26.1.2")
    assert _run_lock_policy(root) == 1
    captured = capsys.readouterr()
    assert "does not match canonical" in captured.err


def test_release_has_single_generic_entrypoint_without_hardcoded_version() -> None:
    workflow_dir = ROOT / ".github" / "workflows"
    assert not (workflow_dir / "release-v2-tag.yml").exists()
    publish = (workflow_dir / "publish.yml").read_text(encoding="utf-8")
    for stale_marker in ("2.0.0", "v2.0.0"):
        assert stale_marker not in publish
    publish_workflows = [path.name for path in workflow_dir.glob("*.yml") if "publish" in path.name]
    assert publish_workflows == ["publish.yml"]


def test_publish_fails_closed_on_tag_version_mismatch() -> None:
    publish = (ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
    assert 'test "$release_tag" = "v$version"' in publish
    assert 'test "$(git rev-parse "refs/tags/$release_tag^{commit}")" = "$release_sha"' in publish


def test_publish_existing_release_is_idempotent() -> None:
    publish = (ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
    assert 'if gh release view "$RELEASE_TAG" >/dev/null 2>&1; then' in publish
    assert "GitHub Release already exists" in publish
