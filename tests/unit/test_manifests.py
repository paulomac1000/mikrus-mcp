from mikrus_mcp.config import Settings, TargetConfig
from mikrus_mcp.manifests import MANIFESTS, active_names, validate_manifests


def settings() -> Settings:
    target = TargetConfig(
        "srv",
        "mikrus",
        api_url="https://api.mikr.us",
        api_key="k",
        server_id="srv",
    )
    return Settings({"srv": target}, "srv")


def test_every_mutation_is_conservative() -> None:
    for manifest in MANIFESTS.values():
        if manifest.side_effects != "read":
            assert manifest.retryable is False
            assert manifest.idempotent is False
            assert manifest.requires_approval is True
            assert manifest.concurrent_safe is False
            assert manifest.timeout_ms >= 65_000


def test_sensitive_reads_declare_confidentiality() -> None:
    assert MANIFESTS["get_db_info"].confidentiality == "credential"
    assert MANIFESTS["read_file"].confidentiality == "sensitive"
    assert MANIFESTS["get_network_info"].confidentiality == "sensitive"


def test_general_purpose_command_execution_has_no_manifest() -> None:
    assert "execute_command" not in MANIFESTS
    assert "execute_command" not in active_names(settings())


def test_manifest_validation_fails_on_registration_drift() -> None:
    current = settings()
    validate_manifests(active_names(current), current)
    try:
        validate_manifests(active_names(current) - {"get_server_info"}, current)
    except RuntimeError as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("registration drift was accepted")


def test_retry_and_concurrency_fields_are_executable_policy() -> None:
    for manifest in MANIFESTS.values():
        assert manifest.concurrent_safe is (manifest.concurrency_scope == "none")
        assert manifest.retryable is bool(manifest.retry_conditions)
        if manifest.retry_conditions:
            assert manifest.idempotent is True
