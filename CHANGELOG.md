# Changelog

All notable changes to mikrus-mcp.

## [Unreleased]

### Fixed

- FastMCP 1.27 lifespan per-connection issue — `_init_clients()` initializes clients globally before SSE/REST bridge startup, REST bridge no longer returns 503 on tool calls
- MCPWrapper and REST bridge tuple result handling for FastMCP 1.27+
- Docker healthcheck replaced NO-OP `sys.exit(0)` with dynamic check against `MCP_REST_PORT/health`
- REST bridge routes added without `/api` prefix (`/health`, `/tools`, `/tools/{name}`) for smoke test compatibility

### Added

- AFDS documentation integration — YAML frontmatter in AGENTS.md, structured sections, pre-commit hook with `scripts/docs_validate.py`, CI validation step
- Log sanitizer (`sanitizer.py`) — redacts API keys, passwords, IPs, MACs from log output
- `isinstance` type checks in all `system.py` and `container_journal.py` internal functions
- `tests/_env_loader.py` for shared environment loading across test suites
- 13 unit tests for `rest_bridge.py` (0% → >80% coverage)
- `.pre-commit-config.yaml` with ruff, mypy, bandit, AFDS validate hooks

### Changed

- `app_lifespan()` is now a thin wrapper — client lifecycle managed globally via `run_stdio()` / `_run_sse_with_rest()`
- Coverage: 89% overall (was 73%), tools/ subdirectory: 93%
- Response helpers location documented: `tools/response.py` (not `server.py`)

## [0.2.0] — 2026-05-08

### Breaking

- All 32 tools now return `{"success": true/false, "data": ..., "error": ...}` instead of raw JSON. AI clients and test assertions must unwrap the `data` key on success and check `error` on failure.

### Added

- Response wrapper helpers `_success_response()` and `_error_response()` in `tools/response.py`
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

- 32 MCP tools: 1 discovery + 12 mikr.us API + 19 system management
- Multi-server support (mikr.us API + SSH backends) via `MCP_SERVERS` JSON config
- stdio + SSE transport with partial startup graceful degradation
- Centralized input validation (`validators.py`)
- 206 unit tests with respx HTTP mocking
- Docker support with CI/CD pipelines
