"""Unit tests for input validators — write guard, command validation.

[RULE: TEST-HIERARCHY-2] Zero I/O — all tests use env var manipulation only.
"""

import os

import pytest

from mikrus_mcp.validators import (
    ValidationError,
    WriteOperationsDisabledError,
    check_write_enabled,
    validate_command,
)


class TestWriteGuard:
    """Tests for the server-level write operations gate (L2+)."""

    def test_check_write_enabled_raises_when_disabled(self) -> None:
        """Write guard blocks operations when ENABLE_WRITE_OPERATIONS is not set."""
        os.environ.pop("ENABLE_WRITE_OPERATIONS", None)
        with pytest.raises(WriteOperationsDisabledError):
            check_write_enabled()

    def test_check_write_enabled_raises_when_set_to_zero(self) -> None:
        """Write guard blocks operations when ENABLE_WRITE_OPERATIONS=0."""
        os.environ["ENABLE_WRITE_OPERATIONS"] = "0"
        with pytest.raises(WriteOperationsDisabledError):
            check_write_enabled()

    def test_check_write_enabled_passes_when_enabled(self) -> None:
        """Write guard allows operations when ENABLE_WRITE_OPERATIONS=1."""
        os.environ["ENABLE_WRITE_OPERATIONS"] = "1"
        check_write_enabled()  # should not raise


class TestValidateCommand:
    """Tests for shell metacharacter validation (L2+)."""

    def test_rejects_empty_command(self) -> None:
        with pytest.raises(ValidationError, match="cannot be empty"):
            validate_command("")

    def test_rejects_non_string_command(self) -> None:
        with pytest.raises(ValidationError, match="cannot be empty"):
            validate_command(None)  # type: ignore[arg-type]

    def test_rejects_semicolon(self) -> None:
        with pytest.raises(ValidationError, match="unsafe characters"):
            validate_command("ls; rm -rf /")

    def test_rejects_pipe(self) -> None:
        with pytest.raises(ValidationError, match="unsafe characters"):
            validate_command("cat /etc/passwd | mail someone")

    def test_rejects_backtick(self) -> None:
        with pytest.raises(ValidationError, match="unsafe characters"):
            validate_command("echo `id`")

    def test_rejects_dollar_sign(self) -> None:
        with pytest.raises(ValidationError, match="unsafe characters"):
            validate_command("echo $(whoami)")

    def test_rejects_ampersand(self) -> None:
        with pytest.raises(ValidationError, match="unsafe characters"):
            validate_command("sleep 10 &")

    def test_rejects_single_quote(self) -> None:
        with pytest.raises(ValidationError, match="unsafe characters"):
            validate_command("echo 'hello'")

    def test_rejects_double_quote(self) -> None:
        with pytest.raises(ValidationError, match="unsafe characters"):
            validate_command('echo "hello"')

    def test_rejects_backslash(self) -> None:
        with pytest.raises(ValidationError, match="unsafe characters"):
            validate_command("echo \\")

    def test_rejects_newline(self) -> None:
        with pytest.raises(ValidationError, match="unsafe characters"):
            validate_command("echo\nrm -rf /")

    def test_rejects_redirect(self) -> None:
        with pytest.raises(ValidationError, match="unsafe characters"):
            validate_command("cat /etc/passwd > /tmp/out")

    def test_rejects_parentheses(self) -> None:
        with pytest.raises(ValidationError, match="unsafe characters"):
            validate_command("(echo test)")

    def test_rejects_curly_braces(self) -> None:
        with pytest.raises(ValidationError, match="unsafe characters"):
            validate_command("{ echo test; }")

    def test_rejects_brackets(self) -> None:
        with pytest.raises(ValidationError, match="unsafe characters"):
            validate_command("[ -f /tmp/test ]")

    def test_rejects_asterisk(self) -> None:
        with pytest.raises(ValidationError, match="unsafe characters"):
            validate_command("rm *")

    def test_rejects_question_mark(self) -> None:
        with pytest.raises(ValidationError, match="unsafe characters"):
            validate_command("ls /tmp/?")

    def test_rejects_exclamation_mark(self) -> None:
        with pytest.raises(ValidationError, match="unsafe characters"):
            validate_command("!ls")

    def test_rejects_tilde(self) -> None:
        with pytest.raises(ValidationError, match="unsafe characters"):
            validate_command("ls ~")

    def test_rejects_angle_brackets(self) -> None:
        with pytest.raises(ValidationError, match="unsafe characters"):
            validate_command("cat < /etc/passwd")

    def test_accepts_simple_command(self) -> None:
        result = validate_command("df -h")
        assert result == "df -h"

    def test_accepts_command_with_numbers(self) -> None:
        result = validate_command("tail -50 /var/log/syslog")
        assert result == "tail -50 /var/log/syslog"

    def test_accepts_command_with_underscore(self) -> None:
        result = validate_command("systemctl status nginx")
        assert result == "systemctl status nginx"
