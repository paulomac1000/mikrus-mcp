# Changelog

All notable changes to mikrus-mcp.

## [1.1.0] — 2026-05-17

### Added

- `describe_mikrus_capabilities` — zero-I/O MCP introspection tool exposing the full tool catalog with capability manifests over MCP/SSE transport (standard rule 2b, L3+)
- `WriteOperationsDisabledError` and `check_write_enabled()` — server-level write guard (standard Write Guard, L2+)
- `validate_command()` — shell metacharacter validation (`;`, `|`, `$`, `` ` ``) for `execute_command` (standard Command Execution Allowlist, L2+)
- `ENABLE_WRITE_OPERATIONS` environment variable (default: disabled) — gates all write/destructive/command tools
- Manifest factory functions (`_make_read_manifest`, `_make_write_manifest`, `_make_destructive_manifest`, `_make_dangerous_manifest`, `_make_sensitive_manifest`) replacing 28 ad-hoc dicts
- `READ_ONLY_SERVICE_ACTIONS` frozenset — `manage_service` skips write guard for `status`/`is-active`/`is-enabled` actions
- `manage_process` skips write guard for `list` action
- Per-tool `_meta` envelope with `request_id`, `duration_ms`, `tool_version` on all responses
- 39 new unit tests: capabilities (5), validators (10), registration (2), manifests/_meta (4), tool count (3 updates), misc (15)

### Changed

- `manage_service` reclassified from `[WRITE]` to `[DESTRUCTIVE]` (service stop/restart causes outage — standard rule: "NEVER classify a service restart as WRITE")
- `manage_process` reclassified to `_make_destructive_manifest` (kill is irreversible)
- `boost_server`, `assign_domain`, `write_file` manifests now use factory functions with corrected `idempotent`/`retryable`/`reversible` fields
- `update_system` remains `[WRITE]` (apt operations are reversible), classified via `_make_write_manifest`
- Error codes unified to standard set: `SSH_ERROR` → `INTERNAL_ERROR`, `API_ERROR` → `HTTP_ERROR`, `OPERATION_FAILED` → `INTERNAL_ERROR`
- `TOOL_MANIFESTS` built exclusively through factory functions — no ad-hoc path remains
- `TOOLS_VERSION` bumped to `1.1.0`
- REST bridge `run_rest_bridge()` now accepts `host` parameter (was hardcoded to `127.0.0.1` — broke Docker port forwarding)
- Unit test conftest enables `ENABLE_WRITE_OPERATIONS=1` for tool logic testing
- Tool count: 32 → 33. All references updated in tests, CI, README, smoke, and e2e

### Fixed

- Write guard now enforced: all 8 mutating tools (`execute_command`, `write_file`, `manage_service`, `manage_process`, `update_system`, `restart_server`, `boost_server`, `assign_domain`) call `check_write_enabled()` before I/O
- `test_rest_bridge.py` and `test_critical_tools.py` hardcoded tool count fixed (32 → 33)
- Ruff format fix in `test_tool_registration.py`

## [1.0.0] — 2026-05-11

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
