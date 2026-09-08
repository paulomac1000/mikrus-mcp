"""Immutable build and runtime identity exposed by the application contract."""

from __future__ import annotations

import os
import platform
import uuid
from functools import lru_cache
from typing import Final

from mikrus_mcp import __version__

_UNKNOWN: Final = "unknown"


@lru_cache(maxsize=1)
def runtime_provenance() -> dict[str, str]:
    return {
        "serviceVersion": __version__,
        "sourceRevision": os.getenv("MIKRUS_MCP_SOURCE_REVISION", _UNKNOWN),
        "buildId": os.getenv("MIKRUS_MCP_BUILD_ID", _UNKNOWN),
        "artifactDigest": os.getenv("MIKRUS_MCP_ARTIFACT_DIGEST", _UNKNOWN),
        "builtAt": os.getenv("MIKRUS_MCP_BUILT_AT", _UNKNOWN),
        "configRevision": os.getenv("MIKRUS_MCP_CONFIG_REVISION", _UNKNOWN),
        "instanceGeneration": os.getenv(
            "MIKRUS_MCP_INSTANCE_GENERATION", f"process-{uuid.uuid4()}"
        ),
        "python": platform.python_version(),
    }
