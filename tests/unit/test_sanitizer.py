from mikrus_mcp.sanitizer import sanitize_data, sanitize_text


def test_sensitive_dictionary_keys_are_redacted() -> None:
    result = sanitize_data(
        {
            "password": "plain-secret",
            "nested": {"api_key": "k", "name": "database"},
            "tokens": [{"authorization": "Basic abc"}],
        }
    )
    assert result == {
        "password": "<REDACTED>",
        "nested": {"api_key": "<REDACTED>", "name": "database"},
        "tokens": [{"authorization": "<REDACTED>"}],
    }


def test_text_tokens_are_redacted() -> None:
    assert "abc" not in sanitize_text("Bearer abc")


def test_network_diagnostics_are_not_destroyed_by_blanket_ip_redaction() -> None:
    value = "127.0.0.1 and 2001:db8::1"
    assert sanitize_text(value) == value
