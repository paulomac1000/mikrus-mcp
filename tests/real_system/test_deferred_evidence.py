"""Provider- or real-system-backed acceptance checks left for the deployment agent."""

import pytest


@pytest.mark.real_backend
@pytest.mark.skip(
    reason=(
        "TODO(real-system): verify stable SSH host fingerprint enrollment "
        "and revalidation"
    )
)
def test_real_ssh_identity_revalidation() -> None:
    pass


@pytest.mark.real_backend
@pytest.mark.skip(
    reason=(
        "TODO(real-system): exercise every mikr.us mutation once and reconcile "
        "ambiguous outcomes"
    )
)
def test_real_mikrus_mutation_reconciliation() -> None:
    pass


@pytest.mark.real_backend
@pytest.mark.skip(
    reason=(
        "TODO(real-system): verify symlink-swap and TOCTOU resistance on the "
        "actual remote filesystem"
    )
)
def test_remote_filesystem_symlink_race() -> None:
    pass


@pytest.mark.artifact
@pytest.mark.skip(
    reason=(
        "TODO(provider): install and test exact wheels on macOS arm64 and "
        "Windows x64"
    )
)
def test_cross_platform_exact_artifact_matrix() -> None:
    pass


@pytest.mark.artifact
@pytest.mark.skip(
    reason=(
        "TODO(provider): smoke the pushed multi-architecture OCI digest on "
        "amd64 and arm64"
    )
)
def test_published_multiarch_image_digest() -> None:
    pass


@pytest.mark.artifact
@pytest.mark.skip(
    reason=(
        "TODO(provider): resolve and verify complete platform-specific "
        "transitive dependency locks with hashes"
    )
)
def test_hashed_transitive_dependency_locks() -> None:
    pass
