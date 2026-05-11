---
description: Agent guidelines and coding standards for the mikrus-mcp MCP server — universal standards, test hierarchy, response format, common pitfalls
doc_id: ref.agent-guidelines
type: ref
status: active
ttl_days: 180
rigor_tier: L2
stability: stable
ai_scope: editable
domain: mcp
tags: ["agents", "coding-standards", "testing", "mcp", "pitfalls"]
owners: ["backend-team"]
upstream:
  - ref.mcp-server-standards
source_of_truth: true
last_verified: "2026-05-10"
---

# Agent Guidelines

> **Universal standards:** See `/var/apps/docs/mcp_standards.md` for reusable MCP server patterns (test hierarchy, response format, CI pipelines, common pitfalls). This file applies those standards to the mikrus-mcp codebase specifically.

## Purpose

This is an MCP (Model Context Protocol) server for managing VPS servers via the [mikr.us](https://mikr.us) API **and** remote Linux servers over SSH. It is written in Python and runs either locally or inside Docker.

## Scope

This document defines coding standards, test requirements, documentation conventions, and operational guidelines for AI coding agents working on the mikrus-mcp codebase. It applies to all source files, test files, documentation, and CI/CD configurations in this repository.

## Definitions

- `MCP tool`: A function exposed by this server that returns a structured JSON response with a `"success"` boolean.
- `internal function`: A private function (`_function_name`) that implements the actual logic without MCP infrastructure.
- `lifespan`: The application lifecycle context that initializes and provides access to backend clients.
- `SSOT (Single Source of Truth)`: A principle requiring each configuration default to be defined in exactly one location.
- `response wrapper`: Helper functions that format every tool response consistently.
- `REST bridge`: An optional HTTP wrapper that exposes MCP tools via REST endpoints for smoke/e2e testing.

## Details

### Architecture

- `src/mikrus_mcp/config.py` — loads configuration from environment variables (`.env`). Supports single-server, multi-server JSON, and SSH-only modes.
- `src/mikrus_mcp/validators.py` — centralized input validation (path, port, service, container, domain, content size, dangerous commands).
- `src/mikrus_mcp/client.py` — async HTTP client for the mikr.us API (`httpx`) + SSH client (`asyncssh`) with certificate support.
- `src/mikrus_mcp/server.py` — MCP server with 32 tools, `stdio` + SSE transport, partial startup graceful degradation.
- `src/mikrus_mcp/rest_bridge.py` — optional REST bridge for smoke/e2e testing; enabled by `MCP_REST_PORT` env var. Exposes `GET /health`, `GET /tools`, `POST /tools/{name}`.
- `src/mikrus_mcp/sanitizer.py` — log sanitization; redacts API keys, passwords, IPs, MACs from response output.
- `src/mikrus_mcp/constants.py` — backward-compatible re-export from `tools/constants.py`.
- `src/mikrus_mcp/tools/constants.py` — SSOT defaults (timeouts, limits, service actions) and `TOOL_MANIFESTS` (32 tool capability descriptors).
- `src/mikrus_mcp/tools/response.py` — `_success_response`, `_error_response`, `_error_response_extended`, `_tool_description` helpers.
- `src/mikrus_mcp/tools/mikrus_api.py` — 12 mikr.us API tools with internal functions and registration.

### Build & Run

```bash
# Local development
pip install -e ".[dev]"
pytest tests/unit/ -q
ruff check src/ tests/
mypy src/
bandit -r src/

# Docker
docker build -t mikrus-mcp .
docker run --rm --env-file .env mikrus-mcp
```

### File Organization

```
tests/
├── conftest.py              # Root: env loading only (~15 lines)
├── fixtures.py              # All mock data constants
├── _env_loader.py           # Shared env loading helper
│
├── unit/
│   ├── conftest.py          # Unit fixtures (mock_client, mock_ssh_client, etc.)
│   ├── test_client.py       # HTTP client tests
│   ├── test_config.py       # Configuration loader tests
│   ├── test_server_tools.py  # Tool handler tests
│   ├── test_ssh_client.py   # SSH client tests
│   ├── test_multi_server.py # Multi-server routing tests
│   ├── test_rest_bridge.py  # REST bridge endpoint tests
│   ├── test_sanitizer.py    # Log sanitization tests
│   └── test_tool_registration.py  # Tool registration verification
│
├── smoke/
│   ├── conftest.py          # Minimal: env loading + skipif
│   ├── test_connectivity.py # API reachable, health check
│   ├── test_critical_tools.py  # Key tools return success
│   └── test_response_format.py # Success field compliance
│
├── integration/
│   ├── conftest.py          # Real credentials + skipif
│   ├── mcp_wrapper.py       # FastMCP abstraction wrapper
│   └── test_real_tools.py   # Tools against real mikr.us API
│
└── e2e/
    ├── conftest.py          # Env loading + skipif
    └── test_server_api.py   # Workflow + error handling tests
```

## Rules

### Language & Naming

#### Mandatory English
- ALL code, comments, docstrings, commit messages, and tool descriptions MUST be in English.
- No Polish, no mixed-language fragments.
- No Polish characters in source files.

#### Tool Descriptions
- First line of `@mcp.tool()` docstring MUST be a complete sentence describing what the tool does.
- NO emoji in tool description first lines.
- NO emoji in API response strings (status labels, messages).
- Every docstring must include `Args` and `Returns` sections.
- Use plain text status labels: `"OK"` not emoji-prefixed labels.
- Tool descriptions MUST include a risk prefix as the first text:
  - `[DANGEROUS]` — executes arbitrary shell commands
  - `[WRITE]` — modifies server state or files
  - `[DESTRUCTIVE]` — kills processes or deletes data
  - `[SENSITIVE]` — returns credentials or tokens
  - No prefix implies `[READ]` — read-only, no side effects

#### Parameter Descriptions
- Use `e.g.` for examples.
- Examples must use generic, non-culture-specific paths and names.

### Test Standards

#### Test Hierarchy

| Suite | Location | Runtime | Requires | Run with |
|-------|----------|---------|----------|----------|
| **Unit** | `tests/unit/` | <20s | Nothing | `pytest tests/unit/ -q` |
| **Smoke** | `tests/smoke/` | <5s | mikr.us API + `MIKRUS_API_KEY` | `pytest tests/smoke/ -q` |
| **Integration** | `tests/integration/` | ~30s | Real API + `MIKRUS_API_KEY` | `pytest tests/integration/ -q` |
| **E2E** | `tests/e2e/` | ~10s | Real API (mocked) | `pytest tests/e2e/ -q` |

#### Test Rules

1. **Unit tests:** Zero I/O, all dependencies mocked via `unittest.mock.patch` or `respx`. Run without credentials.
2. **Smoke tests:** Direct REST API calls (`httpx`), no MCP wrapper needed. Skip if no `MIKRUS_API_KEY`.
3. **Integration tests:** Real mikr.us API calls via `httpx`. Skip if no `MIKRUS_API_KEY`.
4. **E2E tests:** Full pipeline with mocked responses. Test workflow sequences and error handling.
5. **Test isolation:** Each test must be independent. Do not rely on shared state or test order.
6. **Skip, don't fail:** All non-unit tests use `pytest.mark.skipif(not MIKRUS_API_KEY, ...)`.

#### Test Environment

1. Copy `.env.example` to `.env`
2. Fill in `MIKRUS_API_KEY` and `MIKRUS_SERVER_NAME`
3. `.env` is gitignored — never committed

### Code Quality

#### Tool Response Format
- All tools return JSON strings with `{"success": True/False, ...}` structure.
- On success: `{"success": True, "data": <result>}`.
- On failure: `{"success": False, "error": "<message>"}`.
- Use helper functions `_success_response()` and `_error_response()` in `tools/response.py`.
- Never raise unhandled exceptions — catch and return error response.

#### Input Validation
- All input validation is centralized in `validators.py`.
- Validate required parameters early — never pass `None` to string operations.
- Check for empty strings, wrong types, path traversal, dangerous commands before use.

#### Logging
- Use `logging` module instead of `print()`.
- Never log `MIKRUS_API_KEY`, passwords, or API keys.
- Log to `stderr` in compliance with MCP specification.

#### Security
- `.env` is gitignored — never commit credentials.
- Path traversal blocked in `validators.py` — `..` and `~` rejected.
- Dangerous shell commands (`rm -rf /`, `mkfs`, `dd if=`, fork bombs) blocked.
- `sudo_password` fed via stdin, never through shell string interpolation.

### Coverage Requirements

| Requirement | Threshold |
|-------------|-----------|
| Per-module minimum | 80% |
| Overall coverage | >85% |
| New tool unit tests | >80% of new lines |
| New tool smoke test | At least 1 |
| Critical tool (server info, stats, logs) | Unit + smoke + integration |

## Pitfalls

1. **Response format:** Every tool must return `{"success": True/False, ...}`. Tests verify this.
2. **Fixture resolution:** Pytest auto-discovers only `conftest.py` files, NOT `__init__.py`. Put test fixtures in `conftest.py`.
3. **Duplicate fixtures:** Two test files in the same directory cannot define fixtures with the same name in different files. Use common fixtures in `conftest.py`.
4. **SSH mock pattern:** SSH tests use `MagicMock + patch.dict("sys.modules", {"asyncssh": mock})` pattern.
5. **Error swallowing:** Catch all exceptions in tool handlers — a single unhandled exception takes down the MCP server.
6. **MCP context outside request:** `mcp.get_context()` returns `None` outside an active MCP request. Unit tests MUST mock the context via `patch.object(mcp, "get_context", return_value=mock_ctx)` to call tool handlers directly.
7. **Lifespan timing:** The REST bridge starts before `app_lifespan`. The lifespan context is stored in `mcp._lifespan_data` during the lifespan. Tools need this context via `_get_client()`.
8. **Parameterized arg unpacking:** Use `*args` not `**kwargs` for positional parameterized test parameters. Define tuples as `(tool_fn, method_name, ("arg1", "arg2"))`.
9. **Coverage budget:** Unit tests provide 80%+ coverage. Integration adds 5-15%. Smoke and E2E validate format, not coverage metrics.
10. **Placeholder credentials:** Skip conditions for smoke/integration tests MUST also check `== "your_api_key_here"` to prevent tests running with example configuration.
11. **Module-level imports bind early:** Changing `constants.VAR` after import does not propagate to already-imported modules. Set env vars BEFORE importing the module. Use `os.environ` for runtime overrides.
12. **JSON response not parsed:** Always `json.loads()` the tool response before processing. The response is always a JSON string, never a dict.
13. **Response wrapper inconsistency:** Never call `json.dumps()` directly in a tool handler. Always use `_success_response()` or `_error_response()`.
14. **Hardcoded defaults in multiple files:** All config defaults must be in `tools/constants.py` (SSOT). The root `src/mikrus_mcp/constants.py` is a backward-compat re-export only.
15. **Credentials in logs:** Never log `MIKRUS_API_KEY`, passwords, or tokens. If logging dynamic content from tool output, sanitize before writing.
16. **No timeout on external calls:** Every HTTP, SSH, or subprocess call must have a timeout. Without one, a hung backend connection blocks the tool forever.
17. **Public SSE without warning:** Binding SSE to `0.0.0.0` requires `MCP_UNSAFE_PUBLIC_ACCESS_CONFIRMED=1`. Without auth, this exposes full server control to the network.
18. **Framework `call_tool` API mismatch:** `FastMCP.call_tool` is async with `(name, args)`. `Server.call_tool` is sync with `(validate_input=bool)`. Never mix them.
19. **Coverage gap from wrong suite:** Smoke and E2E tests produce 0% coverage by coverage.py. Chasing coverage from these suites is wasted effort. Coverage comes from unit (80%+) and integration (+5-15%) tests.

## Interfaces

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `MCP_SERVERS` / `MIKRUS_SERVERS` | Yes* | JSON object with one or more server configs |
| `MCP_DEFAULT_SERVER` / `MIKRUS_DEFAULT_SERVER` | No | Default server name (auto-picks first if omitted) |
| `MIKRUS_API_KEY` | Yes* | API key from the mikr.us panel (single-server mode) |
| `MIKRUS_SERVER_NAME` | Yes* | Server identifier (single-server mode) |
| `MIKRUS_API_URL` | No | Custom API endpoint (default: `https://api.mikr.us`) |
| `MCP_PORT` | No | Enable SSE transport on this port |
| `MCP_HOST` | No | SSE bind address (default: `127.0.0.1`) |
| `MCP_UNSAFE_PUBLIC_ACCESS_CONFIRMED` | No | Required to bind SSE to `0.0.0.0` |
| `MCP_REST_PORT` | No | Enable optional REST bridge for smoke testing on this port |
| `LOG_LEVEL` | No | Logging level (default: `INFO`) |

*Either `MCP_SERVERS` or `MIKRUS_API_KEY`+`MIKRUS_SERVER_NAME` is required.

### SSH Server Config Fields

| Field | Required | Description |
|-------|----------|-------------|
| `type` | Yes | Must be `"ssh"` |
| `host` | Yes | SSH hostname or IP |
| `port` | No | SSH port (default: 22) |
| `user` | No | SSH username (default: `root`) |
| `password` | No | SSH password |
| `ssh_key` | No | Path to SSH private key |
| `ssh_cert` | No | Path to SSH certificate (signed by CA) |
| `sudo_password` | No | Password for `sudo -S` (journal tools) |
| `timeout` | No | SSH connection timeout in seconds (default: 30) |
| `verify_host_key` | No | Verify SSH host key (default: `false`) |
| `known_hosts_file` | No | Path to known_hosts file |

### Entry Points

- `mikrus-mcp` CLI command (defined in `pyproject.toml`).
- `python -m mikrus_mcp` (via `__main__.py`).

## State

- **Assumptions:** The server has access to the mikr.us API and/or configured SSH hosts. Python 3.11+ is available. The MCP SDK (`mcp`) manages SSE/stdio transport.
- **Constraints:** API rate limits (5 req/min per server). SSH execution limited to ~60 seconds. Unit tests must have zero I/O.
- **Known Limitations:** L3+ features (capability descriptors, tool manifests) are optional. SSE transport security is deployment-specific.

## Edge Cases

- **Missing dependency:** Tool returns structured error response. Server continues operating.
- **Backend unreachable:** `_init_clients()` marks it as failed. Partial startup with remaining backends.
- **Invalid server name:** `_get_client()` raises ValueError. Wrapper returns structured error.

## Examples

Example test file organization, CI pipeline invocation, and common pitfall resolutions can be found in the sections above. See also the test fixtures in `tests/fixtures.py` for mock data patterns.

## Non_Goals

- This document is not a full Python programming guide.
- It does not cover deployment or operations in detail.
- It does not specify HTTP API design outside the MCP tool contract.
