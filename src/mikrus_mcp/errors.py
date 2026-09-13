"""Stable application error taxonomy independent from MCP and upstream SDKs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ErrorCode(StrEnum):
    VALIDATION = "VALIDATION_FAILED"
    AUTHENTICATION = "AUTHENTICATION_FAILED"
    AUTHORIZATION = "AUTHORIZATION_FAILED"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"
    UNAVAILABLE = "UNAVAILABLE"
    TRANSIENT_UPSTREAM = "TRANSIENT_UPSTREAM"
    UPSTREAM_PROTOCOL = "UPSTREAM_PROTOCOL"
    UPSTREAM_REJECTED = "UPSTREAM_REJECTED"
    UPSTREAM = "UPSTREAM_FAILED"
    AMBIGUOUS = "AMBIGUOUS_OUTCOME"
    RECREATE_CONFIG_DRIFT = "RECREATE_CONFIG_DRIFT"
    INTERNAL = "INTERNAL_ERROR"


@dataclass(slots=True)
class AppError(Exception):
    code: ErrorCode
    message: str
    retryable: bool = False
    retry_after_seconds: float | None = None

    def __str__(self) -> str:
        return self.message
