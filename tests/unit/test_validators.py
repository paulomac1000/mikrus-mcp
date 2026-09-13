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
    assert validate_program_executable("grep") == "grep"
    for value in ("/usr/bin/ps", "/tmp/ps", "docker", "sed", "/bin/sh", "ps", "systemctl"):
        with pytest.raises(ValidationError, match="not permitted"):
            validate_program_executable(value)
    with pytest.raises(ValidationError, match="not permitted"):
        validate_program_executable("python3")


def test_content_b64_rejects_non_canonical_and_oversized_payloads() -> None:
    from mikrus_mcp.validators import validate_content_b64

    assert validate_content_b64("") == ""
    assert validate_content_b64("SGVsbG8=") == "SGVsbG8="
    with pytest.raises(ValidationError, match="canonical base64"):
        validate_content_b64("abc")  # length not a multiple of four
    with pytest.raises(ValidationError, match="canonical base64"):
        validate_content_b64("SGVsbG8*")
    with pytest.raises(ValidationError, match="decoded content too large"):
        validate_content_b64("QUJD" * 50_001)  # 150003 decoded bytes


def test_expected_digest_requires_sha256_prefix_and_hex() -> None:
    from mikrus_mcp.validators import validate_expected_digest

    assert validate_expected_digest("sha256:" + "a" * 64) == "sha256:" + "a" * 64
    for value in ("md5:" + "a" * 32, "sha256:" + "g" * 64, "sha256:" + "a" * 63, ""):
        with pytest.raises(ValidationError, match="sha256"):
            validate_expected_digest(value)


def test_cron_profile_id_grammar_is_tight() -> None:
    from mikrus_mcp.validators import validate_cron_profile_id

    assert validate_cron_profile_id("nightly-backup_1") == "nightly-backup_1"
    assert validate_cron_profile_id("a" * 64) == "a" * 64
    for value in ("Upper", "-leading", "with space", "a" * 65, "", "semi;colon"):
        with pytest.raises(ValidationError):
            validate_cron_profile_id(value)


def test_cron_fields_reject_metacharacters_and_out_of_range_values() -> None:
    from mikrus_mcp.validators import validate_cron_field, validate_cron_schedule

    assert validate_cron_field("*/15", "minute") == "*/15"
    assert validate_cron_field("0-30/5", "minute") == "0-30/5"
    assert validate_cron_field("1,15,23", "hour") == "1,15,23"
    assert validate_cron_field("7", "day_of_week") == "7"

    for field, bad in (
        ("minute", "60"),
        ("minute", "*/0"),
        ("hour", "24"),
        ("day_of_month", "0"),
        ("month", "13"),
        ("day_of_week", "8"),
        ("minute", "10-5"),
        ("minute", "0;rm -rf /"),
        ("minute", "0%value"),
        ("minute", "0\n5"),
        ("minute", "jan"),
    ):
        with pytest.raises(ValidationError):
            validate_cron_field(bad, field)

    with pytest.raises(ValidationError, match="exactly"):
        validate_cron_schedule({"minute": "0", "hour": "3"})
    assert validate_cron_schedule(
        {
            "minute": "0",
            "hour": "3",
            "day_of_month": "*",
            "month": "*",
            "day_of_week": "1-5",
        }
    ) == {
        "minute": "0",
        "hour": "3",
        "day_of_month": "*",
        "month": "*",
        "day_of_week": "1-5",
    }


def test_cron_environment_bounds_keys_values_and_size() -> None:
    from mikrus_mcp.validators import validate_cron_environment

    assert validate_cron_environment({"LC_ALL": "C"}) == {"LC_ALL": "C"}
    assert validate_cron_environment(None) == {}
    with pytest.raises(ValidationError):
        validate_cron_environment({"0BAD": "value"})
    with pytest.raises(ValidationError):
        validate_cron_environment({"OK": "line\nbreak"})
    with pytest.raises(ValidationError):
        validate_cron_environment({"OK": "x" * 1025})
    with pytest.raises(ValidationError):
        validate_cron_environment({f"K{i}": "v" for i in range(17)})


def test_typed_program_allowlist_is_strict_and_argv_charset_is_bounded() -> None:
    from mikrus_mcp.validators import validate_program_arguments, validate_program_executable

    for removed in ("systemctl", "printf", "echo", "df", "du", "free", "ls", "ps"):
        with pytest.raises(ValidationError, match="not permitted"):
            validate_program_executable(removed)
    for kept in ("cat", "grep", "ip", "journalctl", "ss", "sort", "tail"):
        assert validate_program_executable(kept) == kept

    assert validate_program_arguments(["--count", "pattern"]) == ["--count", "pattern"]
    for argv in (["two words"], ["semi;colon"], ["pipe|x"], ["a" * 257], ["quoted'arg"]):
        with pytest.raises(ValidationError, match="bounded typed arguments"):
            validate_program_arguments(argv)


def test_cron_numeric_fields_reject_unicode_digits() -> None:
    from mikrus_mcp.validators import validate_cron_field

    with pytest.raises(ValidationError):
        validate_cron_field("*/٥", "minute")
    with pytest.raises(ValidationError):
        validate_cron_field("٥", "minute")
    with pytest.raises(ValidationError):
        validate_cron_field("0-١٠", "hour")
