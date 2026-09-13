from __future__ import annotations

from pathlib import Path

import pytest

from mikrus_mcp.cron_profiles import (
    CronProfileRecord,
    CronProfileStore,
    desired_digest,
    generate_cron_line,
    marker_count,
    marker_line,
    profile_state,
    remove_from_text,
    scan_installed,
    upsert_in_text,
    validate_installed_text,
)
from mikrus_mcp.errors import AppError, ErrorCode

SCHEDULE = {
    "minute": "0",
    "hour": "3",
    "day_of_month": "*",
    "month": "*",
    "day_of_week": "1-5",
}


def record(
    profile_id: str = "backup", *, argv: list[str] | None = None
) -> tuple[CronProfileRecord, str]:
    arguments = ["--count", "pattern"] if argv is None else argv
    generated = generate_cron_line(
        schedule=SCHEDULE,
        executable="grep",
        argv=arguments,
        environment={},
    )
    value = CronProfileRecord(
        profile_id=profile_id,
        principal="principal",
        server_id="host",
        target_identity="ssh:host#host-key=SHA256:x",
        schedule=dict(SCHEDULE),
        executable="grep",
        argv=arguments,
        environment={},
        created_at="2026-09-10T12:00:00Z",
        updated_at="2026-09-10T12:00:00Z",
    ).with_projection(generated)
    return value, generated


def test_generated_line_uses_strict_single_quote_escaping() -> None:
    _, generated = record("quotes")
    assert generated == "0 3 * * 1-5 'grep' '--count' 'pattern'"

    tricky = generate_cron_line(
        schedule=SCHEDULE,
        executable="grep",
        argv=["it's got 'quotes'"],
        environment={},
    )
    assert tricky == "0 3 * * 1-5 'grep' 'it'\\''s got '\\''quotes'\\'''"


def test_generated_line_rejects_percent_and_newlines() -> None:
    from mikrus_mcp.cron_profiles import shell_quote_argument
    from mikrus_mcp.validators import ValidationError

    for unsafe in ("100%", "line\nbreak", "carriage\rreturn", "tab\tvalue"):
        with pytest.raises((AppError, ValidationError)):
            shell_quote_argument(unsafe)


def test_cron_store_round_trips_with_private_permissions(tmp_path: Path) -> None:
    store = CronProfileStore(tmp_path / "cron.json")
    value, _ = record()
    store.upsert(value)
    loaded = store.get(profile_id="backup", principal="principal", server_id="host")
    assert loaded.executable == "grep"
    assert loaded.desired_digest == value.desired_digest
    assert (tmp_path / "cron.json").stat().st_mode & 0o077 == 0

    store.delete(profile_id="backup", principal="principal", server_id="host")
    with pytest.raises(AppError) as missing:
        store.get(profile_id="backup", principal="principal", server_id="host")
    assert missing.value.code == ErrorCode.NOT_FOUND


def test_upsert_is_idempotent_and_preserves_foreign_lines() -> None:
    value, generated = record()
    text = "# editor entry\n0 0 * * * something-else\n"
    once = upsert_in_text(
        text, profile_id=value.profile_id, generated_line=generated, digest=value.desired_digest
    )
    assert once.count(marker_line("backup", value.desired_digest)) == 1
    assert "# editor entry\n" in once
    assert "0 0 * * * something-else\n" in once

    twice = upsert_in_text(
        once, profile_id=value.profile_id, generated_line=generated, digest=value.desired_digest
    )
    assert twice == once


def test_remove_deletes_exactly_one_pair() -> None:
    value, generated = record()
    text = upsert_in_text(
        "# keep\n",
        profile_id=value.profile_id,
        generated_line=generated,
        digest=value.desired_digest,
    )
    other, other_line = record("other", argv=["--version"])
    text = upsert_in_text(
        text, profile_id="other", generated_line=other_line, digest=other.desired_digest
    )

    removed = remove_from_text(text, profile_id=value.profile_id)
    assert "mikrus-mcp:backup" not in removed
    assert generated not in removed
    assert marker_count(scan_installed(removed), "other") == 1
    assert "# keep\n" in removed

    with pytest.raises(AppError) as missing:
        remove_from_text(removed, profile_id=value.profile_id)
    assert missing.value.code == ErrorCode.NOT_FOUND


def test_profile_state_reports_missing_modified_and_duplicated() -> None:
    value, generated = record()
    installed = upsert_in_text(
        "", profile_id="backup", generated_line=generated, digest=value.desired_digest
    )
    observed = scan_installed(installed)
    assert (
        profile_state(
            observed, profile_id="backup", generated_line=generated, digest=value.desired_digest
        )
        == "IN_SYNC"
    )
    assert profile_state(observed, profile_id="absent", generated_line="", digest="0" * 64) == (
        "MISSING"
    )

    tampered = installed.replace(generated, generated.replace("3", "4", 1))
    assert (
        profile_state(
            scan_installed(tampered),
            profile_id="backup",
            generated_line=generated,
            digest=value.desired_digest,
        )
        == "MODIFIED"
    )

    duplicated = installed + installed
    assert (
        profile_state(
            scan_installed(duplicated),
            profile_id="backup",
            generated_line=generated,
            digest=value.desired_digest,
        )
        == "DUPLICATED"
    )


def test_installed_text_bounds_and_binary_rejection() -> None:
    with pytest.raises(AppError) as too_large:
        validate_installed_text("x" * 1_048_577)
    assert too_large.value.code == ErrorCode.UPSTREAM
    with pytest.raises(AppError) as binary:
        validate_installed_text("bad\x00text")
    assert binary.value.code == ErrorCode.UPSTREAM


def test_desired_digest_matches_marker_contract() -> None:
    value, generated = record()
    assert value.desired_digest == desired_digest(generated)
    marker = marker_line("backup", value.desired_digest)
    assert marker == f"# mikrus-mcp:backup:sha256={value.desired_digest}"
