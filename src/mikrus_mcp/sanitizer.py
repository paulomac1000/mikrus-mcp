"""Log sanitization for MCP tool responses.

Redacts sensitive patterns from response data before returning
to the AI agent. Applied at the response boundary.
"""

import re
from typing import Final

_SENSITIVE_PATTERNS: Final[list[tuple[re.Pattern[str], str]]] = [
    (re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE), "Bearer <REDACTED>"),
    (re.compile(r"Authorization:\s*\S+", re.IGNORECASE), "Authorization: <REDACTED>"),
    (re.compile(r"(password|passwd|pwd)[=:]\s*\S+", re.IGNORECASE), r"\1=<REDACTED>"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "<IP_REDACTED>"),
    (
        re.compile(
            r"\b[0-9a-fA-F]{8}[-:][0-9a-fA-F]{4}[-:][0-9a-fA-F]{4}[-:][0-9a-fA-F]{4}[-:][0-9a-fA-F]{12}\b"
        ),
        "<MAC_REDACTED>",
    ),
]


def sanitize_log_line(line: str) -> str:
    """Redact sensitive patterns from a text line.

    Replaces API keys, passwords, tokens, and IP addresses
    with safe placeholders.
    """
    result = line
    for pattern, replacement in _SENSITIVE_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def sanitize_response_data(data: object) -> object:
    """Recursively sanitize a response data structure.

    Walks through dicts and lists, sanitizing all string values.
    """
    if isinstance(data, str):
        return sanitize_log_line(data)
    if isinstance(data, dict):
        return {k: sanitize_response_data(v) for k, v in data.items()}
    if isinstance(data, list):
        return [sanitize_response_data(item) for item in data]
    return data
