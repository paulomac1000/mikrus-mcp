"""Bounded runtime constants retained as a compatibility import surface."""

from typing import Final

from mikrus_mcp import __version__

DEFAULT_HTTP_TIMEOUT: Final = 10.0
EXEC_HTTP_TIMEOUT: Final = 65.0
SSH_DEFAULT_TIMEOUT: Final = 30
MAX_RESPONSE_BYTES: Final = 1_000_000
MAX_PROCESS_OUTPUT_BYTES: Final = 1_000_000
MAX_TAIL_LINES: Final = 500
MAX_JOURNAL_LINES: Final = 500
MAX_SEARCH_RESULTS: Final = 100
MAX_GREP_HOURS: Final = 24
MAX_WRITE_SIZE: Final = 100_000
SERVICE_ACTIONS: Final = frozenset(
    {"status", "start", "stop", "restart", "enable", "disable", "is-active", "is-enabled"}
)
READ_ONLY_SERVICE_ACTIONS: Final = frozenset({"status", "is-active", "is-enabled"})
PROCESS_ACTIONS: Final = frozenset({"list", "kill"})
TOOLS_VERSION: Final = __version__
CAPABILITIES_SCHEMA_VERSION: Final = __version__
