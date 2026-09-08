import pytest

from mikrus_mcp.validators import (
    ValidationError,
    validate_content_size,
    validate_domain,
    validate_hours_param,
    validate_lines_param,
    validate_path,
    validate_port,
    validate_process_target,
    validate_program_executable,
    validate_search_pattern,
    validate_service_action,
    validate_service_name,
)


def test_read_path_rejects_protected_secret_tree() -> None:
    with pytest.raises(ValidationError, match="forbidden"):
        validate_path("/root/.ssh/id_ed25519")


def test_write_path_is_component_aware_and_default_deny() -> None:
    assert validate_path("/tmp/app/config", for_write=True) == "/tmp/app/config"
    with pytest.raises(ValidationError, match="safe roots"):
        validate_path("/tmp-other/file", for_write=True)
    with pytest.raises(ValidationError, match="forbidden"):
        validate_path("/etc/app.conf", for_write=True)


def test_path_rejects_traversal_and_control_characters() -> None:
    for value in ("relative", "/tmp/../etc/passwd", "/tmp/a\x00b"):
        with pytest.raises(ValidationError):
            validate_path(value)


def test_bounded_numeric_parameters_fail_instead_of_clamping() -> None:
    assert validate_lines_param("50") == 50
    assert validate_hours_param("12") == 12
    for value in (0, 501, "bad"):
        with pytest.raises(ValidationError):
            validate_lines_param(value)
    for value in (0, 25, "bad"):
        with pytest.raises(ValidationError):
            validate_hours_param(value)


def test_domain_port_service_process_and_search_validation() -> None:
    assert validate_domain("example.com") == "example.com"
    assert validate_domain("-") == "-"
    assert validate_port("443") == 443
    assert validate_service_name("nginx.service") == "nginx.service"
    assert validate_service_action("restart") == "restart"
    assert validate_process_target("1234") == "1234"
    assert validate_process_target("worker") == "worker"
    assert validate_search_pattern("connection failed") == "connection failed"
    for function, value in (
        (validate_domain, "not a domain"),
        (validate_port, "99999"),
        (validate_service_name, "nginx;id"),
        (validate_service_action, "delete"),
        (validate_process_target, "worker;id"),
        (validate_search_pattern, "x|cat"),
    ):
        with pytest.raises(ValidationError):
            function(value)  # type: ignore[arg-type]


def test_content_limit_counts_encoded_bytes() -> None:
    validate_content_size("a" * 100_000)
    with pytest.raises(ValidationError, match="too large"):
        validate_content_size("ą" * 100_000)


def test_program_executable_is_allowlisted_and_shells_are_rejected() -> None:
    assert validate_program_executable("/usr/bin/docker") == "/usr/bin/docker"
    with pytest.raises(ValidationError, match="not permitted"):
        validate_program_executable("/bin/sh")
    with pytest.raises(ValidationError, match="not permitted"):
        validate_program_executable("python3")
