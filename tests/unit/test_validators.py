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
    # Issue #27 intentionally admits docker/systemctl/curl behind per-executable
    # subcommand policies; shells, paths, and unmanaged tools stay rejected.
    assert validate_program_executable("grep") == "grep"
    for value in ("/usr/bin/ps", "/tmp/ps", "sed", "/bin/sh", "ps", "sh", "bash"):
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


def test_typed_program_executables_admit_diagnostic_programs_per_issue_27() -> None:
    """Issue #27 intentionally transitions executable admission to include
    docker, curl, and systemctl behind per-executable read-only policies;
    unrelated interpreters and general tools stay outside the allowlist."""
    from mikrus_mcp.validators import validate_program_executable

    for removed in ("printf", "echo", "df", "du", "free", "ls", "ps"):
        with pytest.raises(ValidationError, match="not permitted"):
            validate_program_executable(removed)
    for kept in (
        "cat",
        "grep",
        "ip",
        "journalctl",
        "ss",
        "sort",
        "tail",
        "docker",
        "curl",
        "systemctl",
    ):
        assert validate_program_executable(kept) == kept


def test_typed_program_argv_admits_bounded_literal_strings_per_issue_27() -> None:
    """Issue #27 intentionally replaces the argv charset whitelist with bounded
    literal-string admission: any string up to 4096 characters without control
    characters is admitted unchanged, because argv is dispatched without a
    shell. Control-character rejection and size bounds remain mandatory."""
    from mikrus_mcp.validators import validate_program_arguments

    passthrough = [
        "two words",
        "semi;colon",
        "pipe|x",
        "quoted'arg",
        '(dq")',
        "(paren)",
        "{{.Id}}",
        "%{http_code}",
        "--format=short",
    ]
    assert validate_program_arguments(passthrough) == passthrough

    for rejected in (
        [""],
        ["a\x00b"],
        ["a\x1fb"],
        ["a\x7fb"],
        ["a" * 4_097],
        ["\ud800"],
    ):
        with pytest.raises(ValidationError, match="bounded typed arguments"):
            validate_program_arguments(rejected)
    assert validate_program_arguments(["a" * 4_096]) == ["a" * 4_096]

    with pytest.raises(ValidationError, match="at most 128"):
        validate_program_arguments(["x"] * 129)
    with pytest.raises(ValidationError, match="100000-byte"):
        validate_program_arguments(["x" * 4_096] * 25)
    assert validate_program_arguments(["a" * 4_000] * 25) == ["a" * 4_000] * 25
    with pytest.raises(ValidationError, match="bounded typed arguments"):
        validate_program_arguments(["ok", 42])


def test_program_invocation_admits_diagnostic_subcommands_per_issue_27() -> None:
    from mikrus_mcp.validators import validate_program_invocation

    assert validate_program_invocation("docker", ["inspect", "--format", "{{.Id}}", "abc123"]) == [
        "inspect",
        "--format",
        "{{.Id}}",
        "abc123",
    ]
    for argv in (
        ["ps", "-a"],
        ["images"],
        ["logs", "--tail", "10", "web"],
        ["version"],
        ["info"],
        ["stats"],
        ["top"],
        ["--debug", "network", "inspect", "bridge"],
        ["volume", "ls"],
        ["volume", "inspect", "data"],
    ):
        assert validate_program_invocation("docker", argv) == argv

    curl_allowed = (
        ["-q", "-s", "-o", "/dev/null", "-w", "%{http_code}", "https://example.com/status"],
        ["-q", "-sI", "http://example.com/health"],
        ["-q", "-s", "--max-time", "5", "http://example.com/"],
        ["-q", "-s", "-H", "X-Test: 1", "-X", "GET", "https://example.com/api"],
        ["-q", "-I", "--url", "https://example.com/"],
        ["-q", "-s", "-X", "HEAD", "https://example.com/"],
        ["-q", "-s", "https://example.com/"],
        ["--disable", "-s", "https://example.com/"],
    )
    for argv in curl_allowed:
        assert validate_program_invocation("curl", argv) == argv
    with_destinations = ["-q", "-s", "https://api.example.com/v1/status"]
    assert (
        validate_program_invocation(
            "curl", with_destinations, curl_destinations=frozenset({"example.com"})
        )
        == with_destinations
    )

    for argv in (
        ["-s", "-o", "/dev/null", "-w", "%{http_code}", "https://example.com/"],
        ["-q", "-d", "inline=body", "https://example.com/"],
        ["-q", "--data-raw", "x", "https://example.com/"],
        ["-q", "--json", '{"a":1}', "https://example.com/"],
        ["-q", "-F", "a=b", "https://example.com/"],
        ["-q", "-T", "/tmp/f", "https://example.com/"],
        ["-q", "-X", "POST", "https://example.com/"],
        ["-q", "--request", "DELETE", "https://example.com/"],
        ["-q", "--request=PUT", "https://example.com/"],
        ["-q", "-K", "/tmp/curlcfg", "https://example.com/"],
        ["-q", "-Kfile", "https://example.com/"],
        ["-q", "--config", "-", "https://example.com/"],
        ["-q", "--config=/tmp/curlcfg", "https://example.com/"],
        ["-q", "-D", "/tmp/headers", "https://example.com/"],
        ["-q", "--dump-header", "/tmp/headers", "https://example.com/"],
        ["-q", "-c", "/tmp/cookies", "https://example.com/"],
        ["-q", "--cookie-jar", "/tmp/cookies", "https://example.com/"],
        ["-q", "-b", "/tmp/cookies", "https://example.com/"],
        ["-q", "--etag-save", "/tmp/etag", "https://example.com/"],
        ["-q", "--trace", "/tmp/trace", "https://example.com/"],
        ["-q", "--trace-ascii", "/tmp/trace", "https://example.com/"],
        ["-q", "-x", "http://proxy:3128", "https://example.com/"],
        ["-q", "--proxy", "socks5://h:1080", "https://example.com/"],
        ["-q", "--unix-socket", "/var/run.sock", "https://example.com/"],
        ["-q", "-L", "https://example.com/"],
        ["-q", "-w", "@/tmp/format", "https://example.com/"],
        ["-q", "-s", "-H", "@/etc/passwd", "https://example.com/"],
        ["-q", "-s", "--header", "@/etc/passwd", "https://example.com/"],
        ["-q", "-s", "-H", "@-", "https://example.com/"],
        ["-q", "-s", "--header=@/tmp/secret", "https://example.com/"],
        ["-q", "-o", "/tmp/out", "https://example.com/"],
        ["-q", "-s", "file:///etc/passwd"],
        ["-q", "-s", "ftp://example.com/"],
        ["-q", "-s", "example.com"],
        ["-q", "-s", "http://localhost/"],
        ["-q", "-s", "http://127.0.0.1/"],
        ["-q", "-s", "http://[::1]/"],
        ["-q", "-s", "http://169.254.169.254/latest/meta-data/"],
        ["-q", "-s", "http://10.0.0.5/"],
        ["-q", "-s", "http://192.168.1.10/"],
        ["-q", "-s", "http://172.16.0.9/"],
        ["-q", "-s", "http://100.64.0.1/"],
        ["-q", "-s", "http://user@example.com/"],
        ["-q", "-s", "http://service.internal/"],
        ["-q", "-s", "http://host.local/"],
        [],
        ["-s", "https://example.com/"],
    ):
        with pytest.raises(ValidationError, match="PROGRAM_ARGUMENT_NOT_PERMITTED"):
            validate_program_invocation("curl", argv)
    with pytest.raises(ValidationError, match="allowlist"):
        validate_program_invocation(
            "curl",
            ["-q", "-s", "https://other-host.example.net/"],
            curl_destinations=frozenset({"example.com"}),
        )

    for argv in (
        ["status", "nginx"],
        ["--no-pager", "status", "nginx"],
        ["is-active", "nginx"],
        ["is-enabled", "nginx"],
        ["list-units"],
        ["list-unit-files"],
        ["show", "nginx"],
        ["cat", "nginx"],
        ["list-timers"],
        ["is-failed", "nginx"],
    ):
        assert validate_program_invocation("systemctl", argv) == argv

    assert validate_program_invocation("cat", ["two words"]) == ["two words"]


def test_program_invocation_rejects_mutations_with_policy_codes_per_issue_27() -> None:
    from mikrus_mcp.validators import ProgramPolicyError, validate_program_invocation

    for argv in (
        ["rm", "foo"],
        ["run", "nginx"],
        ["exec", "web", "sh"],
        ["rmi", "nginx"],
        ["kill", "web"],
        ["stop", "web"],
        ["start", "web"],
        ["restart", "web"],
        ["build", "."],
        ["push", "image"],
        ["pull", "image"],
        ["cp", "a", "b"],
        ["compose", "up", "-d"],
        ["compose", "down"],
        ["compose", "rm"],
        ["system", "prune"],
    ):
        with pytest.raises(ProgramPolicyError) as docker_error:
            validate_program_invocation("docker", argv)
        assert docker_error.value.policy_code == "PROGRAM_SUBCOMMAND_NOT_PERMITTED"
        assert "docker" in str(docker_error.value)
        assert f"'{argv[0]}'" in str(docker_error.value)

    for argv in (
        ["-T", "backup.tar", "http://example.com"],
        ["--upload-file", "big.bin", "http://example.com"],
        ["-F", "a=b", "http://example.com"],
        ["--form", "a=b", "http://example.com"],
        ["-O", "http://example.com"],
        ["-J", "-s", "http://example.com"],
        ["-o", "/etc/passwd", "http://example.com"],
        ["--output", "/tmp/payload", "http://example.com"],
        ["-ofile", "http://example.com"],
        ["--output=/tmp/payload", "http://example.com"],
        ["-d", "@payload.json", "http://example.com"],
        ["--data", "@payload.json", "http://example.com"],
        ["--data=@payload.json", "http://example.com"],
    ):
        with pytest.raises(ProgramPolicyError) as curl_error:
            validate_program_invocation("curl", argv)
        assert curl_error.value.policy_code == "PROGRAM_ARGUMENT_NOT_PERMITTED"
        assert "curl" in str(curl_error.value)

    for argv in (
        ["restart", "nginx"],
        ["stop", "nginx"],
        ["start", "nginx"],
        ["enable", "nginx"],
        ["disable", "nginx"],
        ["mask", "nginx"],
        ["kill", "nginx"],
        ["reload-or-restart", "nginx"],
    ):
        with pytest.raises(ProgramPolicyError) as systemctl_error:
            validate_program_invocation("systemctl", argv)
        assert systemctl_error.value.policy_code == "PROGRAM_SUBCOMMAND_NOT_PERMITTED"
        assert "systemctl" in str(systemctl_error.value)
        assert f"'{argv[0]}'" in str(systemctl_error.value)


def test_cron_numeric_fields_reject_unicode_digits() -> None:
    from mikrus_mcp.validators import validate_cron_field

    with pytest.raises(ValidationError):
        validate_cron_field("*/٥", "minute")
    with pytest.raises(ValidationError):
        validate_cron_field("٥", "minute")
    with pytest.raises(ValidationError):
        validate_cron_field("0-١٠", "hour")
