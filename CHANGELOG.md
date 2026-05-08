# Changelog

All notable changes to mikrus-mcp.

## [0.2.0] — 2026-05-08

### Breaking

- All 32 tools now return `{"success": true/false, "data": ..., "error": ...}` instead of raw JSON. AI clients and test assertions must unwrap the `data` key on success and check `error` on failure.

### Added

- Response wrapper helpers `_success_response()` and `_error_response()` in `server.py`
- `Args` and `Returns` docstrings for all 32 tool handlers
- Risk-level prefixes on all tool descriptions (`[DANGEROUS]`, `[WRITE]`, `[DESTRUCTIVE]`, `[SENSITIVE]`)
- Optional REST bridge (`rest_bridge.py`) enabled by `MCP_REST_PORT` env var — exposes tools as HTTP endpoints for smoke testing
- `MCP_REST_PORT` environment variable
- 278 unit tests (was 206) covering tool handler success and error paths via mocked MCP context
- Smoke tests: API connectivity (`test_connectivity.py`), critical tool validation (`test_critical_tools.py`), response format compliance (`test_response_format.py`)
- Integration tests: 5 tests against real mikr.us API (`test_real_tools.py`)
- E2E tests: 4 pipeline workflow and error handling tests (`test_server_api.py`)
- `mock_mikrus` and `mock_ssh` fixtures for direct tool handler unit testing
- `mcp_context` fixture with lifespan context mocking

### Changed

- Test structure reorganized from flat `tests/` into `tests/unit/`, `tests/smoke/`, `tests/integration/`, `tests/e2e/`
- `_call_tool_logic` test helper now returns `success`-wrapped responses
- Coverage: overall 86% (was 73%), `server.py` 88% (was 47%)
- AGENTS.md expanded with: universal standards link, tool risk annotation rules, REST bridge info, 10 common pitfalls, `MCP_REST_PORT` env var
- README.md expanded with: Tool Response Format section, risk prefix table, REST bridge usage, updated test commands and architecture diagram
- `pyproject.toml`: fixed Polish character (`ł` → `l`), added ruff per-file-ignore for test E501
- `.env` synced with credentials from `/var/apps/ha-mcp-stack` (gitignored)

### Removed

- `brief.md` (implementation task tracking file)

## [0.1.0] — 2026-05-01

### Initial release

- 32 MCP tools: 13 mikr.us API + 19 system management
- Multi-server support (mikr.us API + SSH backends) via `MCP_SERVERS` JSON config
- stdio + SSE transport with partial startup graceful degradation
- Centralized input validation (`validators.py`)
- 206 unit tests with respx HTTP mocking
- Docker support with CI/CD pipelines
