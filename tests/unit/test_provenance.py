from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from mikrus_mcp import __version__
from mikrus_mcp import provenance as provenance_module
from mikrus_mcp.provenance import capture_runtime_provenance

ROOT = Path(__file__).resolve().parents[2]
SOURCE_PACKAGE = Path(provenance_module.__file__).resolve().parent
SOURCE_REVISION = "a" * 40
BUILD_ID = "github-123-1"
BUILT_AT = "2026-09-08T20:00:00Z"


def copy_package(tmp_path: Path) -> Path:
    package_dir = tmp_path / "mikrus_mcp"
    shutil.copytree(
        SOURCE_PACKAGE,
        package_dir,
        ignore=shutil.ignore_patterns("_build_provenance.json", "__pycache__", "*.pyc", "*.pyo"),
    )
    return package_dir


def stamp(package_dir: Path, *, source_revision: str = SOURCE_REVISION) -> None:
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "stamp_build_provenance.py"),
            "--source-revision",
            source_revision,
            "--build-id",
            BUILD_ID,
            "--built-at",
            BUILT_AT,
            "--package-dir",
            str(package_dir),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def write_receipt(
    path: Path,
    *,
    source_revision: str = SOURCE_REVISION,
    build_id: str = BUILD_ID,
    package_content_digest: str,
) -> None:
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "sourceRevision": source_revision,
                "buildId": build_id,
                "packageContentDigest": package_content_digest,
                "imageDigest": "sha256:" + "1" * 64,
                "releaseManifestDigest": "2" * 64,
            }
        ),
        encoding="utf-8",
    )


def test_unstamped_checkout_is_runnable_and_explicit(tmp_path: Path) -> None:
    package_dir = copy_package(tmp_path)

    snapshot = capture_runtime_provenance(package_dir=package_dir, environ={})

    assert snapshot.service_version == __version__
    assert snapshot.source_revision == "unknown"
    assert snapshot.build_id == "unknown"
    assert snapshot.package_content_digest == "unknown"
    assert snapshot.package_integrity == "unstamped"
    assert snapshot.deployment.binding == "missing"


def test_verified_stamp_matches_installed_package_content(tmp_path: Path) -> None:
    package_dir = copy_package(tmp_path)
    stamp(package_dir)

    snapshot = capture_runtime_provenance(package_dir=package_dir, environ={})
    projection = snapshot.as_dict()

    assert snapshot.service_version == __version__
    assert snapshot.source_revision == SOURCE_REVISION
    assert snapshot.build_id == BUILD_ID
    assert snapshot.built_at == BUILT_AT
    assert snapshot.package_integrity == "verified"
    assert snapshot.policy_revision != "unknown"
    assert snapshot.package_content_digest != "unknown"
    assert projection["artifactDigest"] == projection["packageContentDigest"]


def test_tampered_installed_file_fails_package_integrity(tmp_path: Path) -> None:
    package_dir = copy_package(tmp_path)
    stamp(package_dir)
    target = package_dir / "errors.py"
    target.write_text(target.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")

    snapshot = capture_runtime_provenance(package_dir=package_dir, environ={})

    assert snapshot.package_integrity == "failed"


def test_environment_cannot_override_artifact_identity_or_instance_generation(
    tmp_path: Path,
) -> None:
    package_dir = copy_package(tmp_path)
    stamp(package_dir)
    environment = {
        "MIKRUS_MCP_SOURCE_REVISION": "b" * 40,
        "MIKRUS_MCP_BUILD_ID": "attacker-build",
        "MIKRUS_MCP_ARTIFACT_DIGEST": "c" * 64,
        "MIKRUS_MCP_BUILT_AT": "1999-01-01T00:00:00Z",
        "MIKRUS_MCP_INSTANCE_GENERATION": "attacker-instance",
        "MIKRUS_MCP_CONFIG_REVISION": "deployment-config-7",
    }

    snapshot = capture_runtime_provenance(package_dir=package_dir, environ=environment)

    assert snapshot.source_revision == SOURCE_REVISION
    assert snapshot.build_id == BUILD_ID
    assert snapshot.built_at == BUILT_AT
    assert snapshot.package_content_digest != "c" * 64
    assert snapshot.instance_generation != "attacker-instance"
    assert snapshot.config_revision == "deployment-config-7"


def test_instance_generation_is_stable_within_process_and_unique_across_processes(
    tmp_path: Path,
) -> None:
    package_dir = copy_package(tmp_path)
    first = capture_runtime_provenance(package_dir=package_dir, environ={}).instance_generation
    second = capture_runtime_provenance(package_dir=package_dir, environ={}).instance_generation
    assert first == second
    assert first.startswith("process-")
    uuid.UUID(first.removeprefix("process-"))

    code = (
        "from mikrus_mcp.provenance import runtime_provenance; "
        "print(runtime_provenance()['instanceGeneration'])"
    )
    environment = dict(os.environ)
    environment.pop("MIKRUS_MCP_INSTANCE_GENERATION", None)
    child_one = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    ).stdout.strip()
    child_two = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    ).stdout.strip()
    assert child_one != child_two


def test_matching_deployment_receipt_is_verified(tmp_path: Path) -> None:
    package_dir = copy_package(tmp_path)
    stamp(package_dir)
    embedded = capture_runtime_provenance(package_dir=package_dir, environ={})
    receipt = tmp_path / "deployment-receipt.json"
    write_receipt(receipt, package_content_digest=embedded.package_content_digest)

    snapshot = capture_runtime_provenance(
        package_dir=package_dir,
        receipt_path=receipt,
        environ={},
    )

    assert snapshot.deployment.binding == "verified"
    assert snapshot.deployment.image_digest == "sha256:" + "1" * 64
    assert snapshot.deployment.release_manifest_digest == "sha256:" + "2" * 64


def test_mismatched_deployment_receipt_is_invalid_and_does_not_echo_digests(
    tmp_path: Path,
) -> None:
    package_dir = copy_package(tmp_path)
    stamp(package_dir)
    embedded = capture_runtime_provenance(package_dir=package_dir, environ={})
    receipt = tmp_path / "deployment-receipt.json"
    write_receipt(
        receipt,
        build_id="different-build",
        package_content_digest=embedded.package_content_digest,
    )

    snapshot = capture_runtime_provenance(
        package_dir=package_dir,
        receipt_path=receipt,
        environ={},
    )

    assert snapshot.deployment.binding == "invalid"
    assert snapshot.deployment.image_digest == "unknown"
    assert snapshot.deployment.release_manifest_digest == "unknown"


def test_absent_deployment_receipt_is_missing(tmp_path: Path) -> None:
    package_dir = copy_package(tmp_path)
    stamp(package_dir)

    snapshot = capture_runtime_provenance(
        package_dir=package_dir,
        receipt_path=tmp_path / "missing-receipt.json",
        environ={},
    )

    assert snapshot.package_integrity == "verified"
    assert snapshot.deployment.binding == "missing"


def test_stamped_revision_rejects_deployment_receipt_of_other_revision(
    tmp_path: Path,
) -> None:
    revision_a = SOURCE_REVISION
    revision_b = "c" * 40
    package_a = copy_package(tmp_path / "pkg-a")
    package_b = copy_package(tmp_path / "pkg-b")
    stamp(package_a, source_revision=revision_a)
    stamp(package_b, source_revision=revision_b)
    embedded_a = capture_runtime_provenance(package_dir=package_a, environ={})
    embedded_b = capture_runtime_provenance(package_dir=package_b, environ={})
    assert embedded_a.source_revision == revision_a
    assert embedded_b.source_revision == revision_b

    receipt_a = tmp_path / "receipt-a.json"
    receipt_b = tmp_path / "receipt-b.json"
    write_receipt(
        receipt_a,
        package_content_digest=embedded_a.package_content_digest,
        source_revision=revision_a,
    )
    write_receipt(
        receipt_b,
        package_content_digest=embedded_b.package_content_digest,
        source_revision=revision_b,
    )

    wrong_receipt_for_a = capture_runtime_provenance(
        package_dir=package_a,
        receipt_path=receipt_b,
        environ={},
    )
    assert wrong_receipt_for_a.deployment.binding == "invalid"
    assert wrong_receipt_for_a.deployment.image_digest == "unknown"
    assert wrong_receipt_for_a.deployment.release_manifest_digest == "unknown"
    assert revision_b not in json.dumps(wrong_receipt_for_a.as_dict())

    wrong_receipt_for_b = capture_runtime_provenance(
        package_dir=package_b,
        receipt_path=receipt_a,
        environ={},
    )
    assert wrong_receipt_for_b.deployment.binding == "invalid"
    assert wrong_receipt_for_b.deployment.image_digest == "unknown"
    assert wrong_receipt_for_b.deployment.release_manifest_digest == "unknown"
    assert revision_a not in json.dumps(wrong_receipt_for_b.as_dict())

    matching_a = capture_runtime_provenance(
        package_dir=package_a,
        receipt_path=receipt_a,
        environ={},
    )
    assert matching_a.deployment.binding == "verified"
