"""Immutable build and runtime identity exposed by the application contract."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import platform
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final, Literal

from mikrus_mcp import __version__

_UNKNOWN: Final = "unknown"
_BUILD_PROVENANCE_FILE: Final = "_build_provenance.json"
_DEPLOYMENT_RECEIPT_ENV: Final = "MIKRUS_MCP_DEPLOYMENT_RECEIPT_FILE"
_POLICY_FILES: Final = (
    "manifests.py",
    "kernel_policy.py",
    "validators.py",
    "approvals.py",
)
_SOURCE_REVISION_RE: Final = re.compile(r"[0-9a-f]{40}")
_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}")
_DIGEST_RE: Final = re.compile(r"(?:sha256:)?([0-9a-f]{64})")
_PACKAGE_DIR: Final = Path(__file__).resolve().parent
_INSTANCE_GENERATION: Final = f"process-{uuid.uuid4()}"

PackageIntegrity = Literal["verified", "failed", "unstamped"]
DeploymentBinding = Literal["verified", "missing", "invalid"]


@dataclass(frozen=True, slots=True)
class DeploymentProvenance:
    image_digest: str
    release_manifest_digest: str
    binding: DeploymentBinding

    def as_dict(self) -> dict[str, str]:
        return {
            "imageDigest": self.image_digest,
            "releaseManifestDigest": self.release_manifest_digest,
            "binding": self.binding,
        }


@dataclass(frozen=True, slots=True)
class ProvenanceSnapshot:
    service_version: str
    source_revision: str
    build_id: str
    built_at: str
    policy_revision: str
    package_content_digest: str
    package_integrity: PackageIntegrity
    config_revision: str
    instance_generation: str
    python: str
    deployment: DeploymentProvenance

    def as_dict(self) -> dict[str, object]:
        return {
            "serviceVersion": self.service_version,
            "sourceRevision": self.source_revision,
            "buildId": self.build_id,
            "artifactDigest": self.package_content_digest,
            "builtAt": self.built_at,
            "policyRevision": self.policy_revision,
            "packageContentDigest": self.package_content_digest,
            "packageIntegrity": self.package_integrity,
            "configRevision": self.config_revision,
            "instanceGeneration": self.instance_generation,
            "python": self.python,
            "deployment": self.deployment.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class _EmbeddedBuildIdentity:
    service_version: str
    source_revision: str
    build_id: str
    built_at: str
    policy_revision: str
    package_content_digest: str
    config_revision: str


def _hash_file_set(package_dir: Path, relative_names: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    for relative_name in relative_names:
        path = package_dir / relative_name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"provenance input is not a regular file: {relative_name}")
        digest.update(relative_name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def policy_revision(package_dir: Path = _PACKAGE_DIR) -> str:
    """Return the deterministic policy digest for the policy-owning sources."""
    return _hash_file_set(package_dir, _POLICY_FILES)


def package_content_digest(package_dir: Path = _PACKAGE_DIR) -> str:
    """Hash installed package files, excluding only build provenance and runtime caches."""
    digest = hashlib.sha256()
    files: list[tuple[str, Path]] = []
    for path in package_dir.rglob("*"):
        relative = path.relative_to(package_dir)
        if _BUILD_PROVENANCE_FILE == relative.as_posix():
            continue
        if "__pycache__" in relative.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        if path.is_symlink():
            raise ValueError(f"package content contains a symlink: {relative.as_posix()}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError(f"package content is not a regular file: {relative.as_posix()}")
        files.append((relative.as_posix(), path))
    if not files:
        raise ValueError("package content is empty")
    for relative_name, path in sorted(files):
        digest.update(relative_name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _load_json_object(path: Path) -> dict[str, object]:
    loaded: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("provenance JSON must be an object")
    result: dict[str, object] = {}
    for key, value in loaded.items():
        if not isinstance(key, str):
            raise ValueError("provenance JSON keys must be strings")
        result[key] = value
    return result


def _required_string(record: Mapping[str, object], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str):
        raise ValueError(f"provenance field {key!r} must be a string")
    return value


def _valid_built_at(value: str) -> bool:
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _load_embedded_identity(package_dir: Path) -> _EmbeddedBuildIdentity:
    path = package_dir / _BUILD_PROVENANCE_FILE
    if path.is_symlink() or not path.is_file():
        raise ValueError("build provenance record is not a regular file")
    record = _load_json_object(path)
    if record.get("schemaVersion") != 1:
        raise ValueError("unsupported build provenance schema")
    service_version = _required_string(record, "serviceVersion")
    source_revision = _required_string(record, "sourceRevision")
    build_id = _required_string(record, "buildId")
    built_at = _required_string(record, "builtAt")
    policy_digest = _required_string(record, "policyRevision")
    package_digest = _required_string(record, "packageContentDigest")
    config_revision = _required_string(record, "configRevision")
    if service_version != __version__:
        raise ValueError("embedded service version does not match the installed package")
    if _SOURCE_REVISION_RE.fullmatch(source_revision) is None:
        raise ValueError("sourceRevision must be a lowercase 40-hex revision")
    if not build_id.strip() or len(build_id) > 200:
        raise ValueError("buildId must be a non-empty bounded string")
    if not _valid_built_at(built_at):
        raise ValueError("builtAt must be an offset-aware ISO-8601 timestamp")
    if _SHA256_RE.fullmatch(policy_digest) is None:
        raise ValueError("policyRevision must be a lowercase sha256 digest")
    if _SHA256_RE.fullmatch(package_digest) is None:
        raise ValueError("packageContentDigest must be a lowercase sha256 digest")
    if not config_revision or len(config_revision) > 256:
        raise ValueError("configRevision must be a non-empty bounded string")
    return _EmbeddedBuildIdentity(
        service_version=service_version,
        source_revision=source_revision,
        build_id=build_id,
        built_at=built_at,
        policy_revision=policy_digest,
        package_content_digest=package_digest,
        config_revision=config_revision,
    )


def _embedded_identity_and_integrity(
    package_dir: Path,
) -> tuple[_EmbeddedBuildIdentity | None, PackageIntegrity]:
    stamp_path = package_dir / _BUILD_PROVENANCE_FILE
    if not os.path.lexists(stamp_path):
        return None, "unstamped"
    try:
        identity = _load_embedded_identity(package_dir)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return None, "failed"
    try:
        current_package_digest = package_content_digest(package_dir)
        current_policy_revision = policy_revision(package_dir)
    except (OSError, ValueError):
        return identity, "failed"
    verified = hmac.compare_digest(
        identity.package_content_digest, current_package_digest
    ) and hmac.compare_digest(identity.policy_revision, current_policy_revision)
    return identity, "verified" if verified else "failed"


def _canonical_external_digest(value: str) -> str | None:
    match = _DIGEST_RE.fullmatch(value)
    if match is None:
        return None
    return f"sha256:{match.group(1)}"


def _deployment_provenance(
    identity: _EmbeddedBuildIdentity | None,
    integrity: PackageIntegrity,
    receipt_path: Path | None,
) -> DeploymentProvenance:
    if receipt_path is None or not os.path.lexists(receipt_path):
        return DeploymentProvenance(_UNKNOWN, _UNKNOWN, "missing")
    if receipt_path.is_symlink() or not receipt_path.is_file():
        return DeploymentProvenance(_UNKNOWN, _UNKNOWN, "invalid")
    if identity is None or integrity != "verified":
        return DeploymentProvenance(_UNKNOWN, _UNKNOWN, "invalid")
    try:
        receipt = _load_json_object(receipt_path)
        if receipt.get("schemaVersion", 1) != 1:
            raise ValueError("unsupported deployment receipt schema")
        source_revision = _required_string(receipt, "sourceRevision")
        build_id = _required_string(receipt, "buildId")
        package_digest = _required_string(receipt, "packageContentDigest")
        image_digest = _required_string(receipt, "imageDigest")
        release_manifest_digest = _required_string(receipt, "releaseManifestDigest")
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return DeploymentProvenance(_UNKNOWN, _UNKNOWN, "invalid")
    if not (
        hmac.compare_digest(source_revision, identity.source_revision)
        and hmac.compare_digest(build_id, identity.build_id)
        and hmac.compare_digest(package_digest, identity.package_content_digest)
    ):
        return DeploymentProvenance(_UNKNOWN, _UNKNOWN, "invalid")
    canonical_image_digest = _canonical_external_digest(image_digest)
    canonical_release_digest = _canonical_external_digest(release_manifest_digest)
    if canonical_image_digest is None or canonical_release_digest is None:
        return DeploymentProvenance(_UNKNOWN, _UNKNOWN, "invalid")
    return DeploymentProvenance(canonical_image_digest, canonical_release_digest, "verified")


def _config_revision(
    identity: _EmbeddedBuildIdentity | None,
    environ: Mapping[str, str],
) -> str:
    advisory = environ.get("MIKRUS_MCP_CONFIG_REVISION")
    if advisory is not None:
        advisory = advisory.strip()
        if advisory and len(advisory) <= 256:
            return advisory
    return identity.config_revision if identity is not None else _UNKNOWN


def capture_runtime_provenance(
    *,
    package_dir: Path | None = None,
    receipt_path: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> ProvenanceSnapshot:
    """Capture one immutable runtime provenance snapshot."""
    resolved_package_dir = _PACKAGE_DIR if package_dir is None else package_dir
    environment = os.environ if environ is None else environ
    identity, integrity = _embedded_identity_and_integrity(resolved_package_dir)
    configured_receipt = receipt_path
    if configured_receipt is None:
        receipt_value = environment.get(_DEPLOYMENT_RECEIPT_ENV)
        if receipt_value:
            configured_receipt = Path(receipt_value)
    deployment = _deployment_provenance(identity, integrity, configured_receipt)
    return ProvenanceSnapshot(
        service_version=identity.service_version if identity is not None else __version__,
        source_revision=identity.source_revision if identity is not None else _UNKNOWN,
        build_id=identity.build_id if identity is not None else _UNKNOWN,
        built_at=identity.built_at if identity is not None else _UNKNOWN,
        policy_revision=identity.policy_revision if identity is not None else _UNKNOWN,
        package_content_digest=(
            identity.package_content_digest if identity is not None else _UNKNOWN
        ),
        package_integrity=integrity,
        config_revision=_config_revision(identity, environment),
        instance_generation=_INSTANCE_GENERATION,
        python=platform.python_version(),
        deployment=deployment,
    )


def runtime_provenance() -> dict[str, object]:
    """Return a backward-compatible dictionary projection of runtime provenance."""
    return capture_runtime_provenance().as_dict()
