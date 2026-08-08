from __future__ import annotations

from pathlib import Path

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
    assert 'release_tag: ${{ steps.revision.outputs.release_tag }}' in workflow
    assert 'echo "release_tag=$release_tag" >> "$GITHUB_OUTPUT"' in workflow
    assert 'RELEASE_TAG: ${{ needs.validate-release.outputs.release_tag }}' in workflow
    assert 'if [[ -n "$RELEASE_TAG" ]]; then' in workflow
    assert 'version_ref="$repository:$VERSION"' in workflow
