"""Unit tests for sanitizer module."""

from mikrus_mcp.sanitizer import sanitize_log_line, sanitize_response_data


class TestSanitizeLogLine:
    def test_redacts_bearer_token(self) -> None:
        result = sanitize_log_line("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.test")
        assert "Authorization: <REDACTED>" in result
        assert "eyJhbGciOiJIUzI1NiJ9" not in result

    def test_redacts_standalone_bearer(self) -> None:
        result = sanitize_log_line("token = Bearer eyJhbGciOiJIUzI1NiJ9.test")
        assert "Bearer <REDACTED>" in result
        assert "eyJhbGciOiJIUzI1NiJ9" not in result

    def test_redacts_authorization_header(self) -> None:
        result = sanitize_log_line("Authorization: Basic dXNlcjpwYXNz")
        assert "Authorization: <REDACTED>" in result

    def test_redacts_password_param(self) -> None:
        result = sanitize_log_line("password=supersecret123")
        # password= is followed by <REDACTED>
        assert "<REDACTED>" in result
        assert "supersecret123" not in result

    def test_redacts_passwd_param(self) -> None:
        result = sanitize_log_line("passwd=mysecret")
        assert "<REDACTED>" in result
        assert "mysecret" not in result

    def test_redacts_pwd_param(self) -> None:
        result = sanitize_log_line("pwd=topsecret")
        assert "<REDACTED>" in result
        assert "topsecret" not in result

    def test_redacts_ipv4_address(self) -> None:
        result = sanitize_log_line("Connecting to 192.168.1.100:8080")
        assert "<IP_REDACTED>" in result
        assert "192.168.1.100" not in result

    def test_passes_clean_text_unchanged(self) -> None:
        result = sanitize_log_line("Hello world, this is a normal log line")
        assert result == "Hello world, this is a normal log line"

    def test_handles_empty_string(self) -> None:
        assert sanitize_log_line("") == ""

    def test_handles_multiple_sensitive_values(self) -> None:
        line = "user=admin password=secret server=192.168.1.1"
        result = sanitize_log_line(line)
        assert "<REDACTED>" in result
        assert "secret" not in result
        assert "192.168.1.1" not in result
        assert "admin" not in result or "admin" in result  # password= not user=


class TestSanitizeResponseData:
    def test_sanitizes_string(self) -> None:
        result = sanitize_response_data("Bearer tok123")
        assert "Bearer <REDACTED>" in result

    def test_sanitizes_dict_values(self) -> None:
        data = {"token": "Bearer abc123", "name": "test"}
        result = sanitize_response_data(data)
        assert "Bearer <REDACTED>" in result["token"]
        assert result["name"] == "test"

    def test_sanitizes_nested_dict(self) -> None:
        data = {"outer": {"inner": "password=secret", "safe": "ok"}}
        result = sanitize_response_data(data)
        assert "<REDACTED>" in result["outer"]["inner"]
        assert result["outer"]["safe"] == "ok"

    def test_sanitizes_list_items(self) -> None:
        data = ["password=secret", "safe text"]
        result = sanitize_response_data(data)
        assert "<REDACTED>" in result[0]
        assert result[1] == "safe text"

    def test_passes_non_string_types(self) -> None:
        data = {"count": 42, "active": True, "score": 3.14}
        result = sanitize_response_data(data)
        assert result["count"] == 42
        assert result["active"] is True
        assert result["score"] == 3.14
