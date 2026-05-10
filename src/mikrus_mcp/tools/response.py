"""Response helpers and tool description builder.

All tools MUST use these helpers for consistent response formatting.
"""

import json
import uuid
from typing import Any

from mikrus_mcp.sanitizer import sanitize_log_line, sanitize_response_data
from mikrus_mcp.tools.constants import TOOL_MANIFESTS


def _tool_description(name: str, base_description: str) -> str:
    """Build tool description with risk prefix from TOOL_MANIFESTS.

    Risk prefix is dynamically injected from the manifest SSOT.
    READ tools get no prefix, per convention.
    """
    manifest = TOOL_MANIFESTS.get(name, {})
    risk = manifest.get("risk", "READ")
    clean = base_description.strip()
    if risk == "READ":
        return clean
    return f"[{risk}] {clean}"


def _success_response(data: Any, meta: dict[str, Any] | None = None) -> str:
    """Format a successful tool response. Includes _meta envelope when provided."""
    request_id = str(uuid.uuid4())
    response: dict[str, Any] = {"success": True, "data": sanitize_response_data(data)}
    envelope = dict(meta or {})
    envelope.setdefault("request_id", request_id)
    envelope.setdefault("duration_ms", 0)
    envelope.setdefault("cached", False)
    envelope.setdefault("retry_safe", False)
    response["_meta"] = envelope
    return json.dumps(response, indent=2, ensure_ascii=False)


def _error_response(error: str) -> str:
    """Format an error tool response."""
    request_id = str(uuid.uuid4())
    return json.dumps(
        {
            "success": False,
            "error": sanitize_log_line(error),
            "_meta": {"request_id": request_id},
        },
        indent=2,
        ensure_ascii=False,
    )


def _error_response_extended(
    code: str,
    message: str,
    retryable: bool,
    suggestion: str | None = None,
    available_names: list[str] | None = None,
) -> str:
    """Format an extended error response with structured fields (L2+)."""
    request_id = str(uuid.uuid4())
    error: dict[str, Any] = {
        "code": code,
        "message": sanitize_log_line(message),
        "retryable": retryable,
        "request_id": request_id,
    }
    if suggestion:
        error["suggestion"] = suggestion
    if available_names:
        error["available_names"] = available_names
    return json.dumps({"success": False, "error": error}, indent=2, ensure_ascii=False)
