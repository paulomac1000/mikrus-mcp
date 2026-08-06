"""Field-aware minimization and redaction at model-visible and logging boundaries."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Final

_SECRET_KEYS: Final = re.compile(
    r"(?:password|passwd|pwd|secret|token|api[_-]?key|private[_-]?key|cookie|"
    r"authorization|sudo_password)$",
    re.IGNORECASE,
)
_PATTERNS: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    (re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE), "Bearer <REDACTED>"),
    (re.compile(r"Authorization:\s*[^\s,;]+", re.IGNORECASE), "Authorization: <REDACTED>"),
    (
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?"
            r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
        ),
        "<PRIVATE_KEY_REDACTED>",
    ),
    (
        re.compile(r"(?i)\b(password|passwd|pwd|token|secret|api[_-]?key)\s*[=:]\s*\S+"),
        r"\1=<REDACTED>",
    ),
)


def sanitize_text(value: str) -> str:
    result = value
    for pattern, replacement in _PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def sanitize_data(value: object, *, field_name: str | None = None) -> object:
    if field_name and _SECRET_KEYS.search(field_name):
        return "<REDACTED>"
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, Mapping):
        return {
            str(key): sanitize_data(item, field_name=str(key))
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [sanitize_data(item) for item in value]
    return value
