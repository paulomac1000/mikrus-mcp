# Implementation Notes — mikrus-mcp MCP Server Standards Compliance

## Branch
`standardize-response-format-and-test-coverage`

## Summary
Implemented 5 critical compliance gaps inherited from a prior partial implementation: write guard enforcement, command metacharacter validation, capability introspection tool, error code unification, and test coverage for new code.

## Files Changed

### Modified (10 files)
| File | Changes |
|------|---------|
| `.env.example` | Added `ENABLE_WRITE_OPERATIONS` documentation |
| `src/mikrus_mcp/server.py` | Imported and registered `register_capability_tools` |
| `src/mikrus_mcp/tools/constants.py` | (Prior work) Rewrote manifests with factory functions, added `write_operations_enabled()`, `READ_ONLY_SERVICE_ACTIONS`, `CAPABILITIES_SCHEMA_VERSION` |
| `src/mikrus_mcp/tools/container_journal.py` | `API_ERROR` → `HTTP_ERROR` (6 occurrences) |
| `src/mikrus_mcp/tools/mikrus_api.py` | Added `check_write_enabled()` calls to `restart_server_tool`, `boost_server_tool`, `assign_domain_tool`; `API_ERROR` → `HTTP_ERROR` (9 occurrences) |
| `src/mikrus_mcp/tools/system.py` | Added `check_write_enabled()` to `execute_command_tool`, `write_file_tool`, `manage_service_tool` (skip read-only actions), `manage_process_tool` (skip list), `update_system_tool`; added `validate_command()` call; `SSH_ERROR` → `INTERNAL_ERROR`; `API_ERROR` → `HTTP_ERROR`; `OPERATION_FAILED` → `INTERNAL_ERROR` |
| `src/mikrus_mcp/validators.py` | (Prior work) Added `WriteOperationsDisabledError`, `check_write_enabled()`, `SHELL_UNSAFE_CHARS`; added `validate_command()` |
| `tests/unit/conftest.py` | Set `ENABLE_WRITE_OPERATIONS=1` in unit test environment |
| `tests/unit/test_rest_bridge.py` | `tool_count == 32` → `33` |
| `tests/unit/test_tool_registration.py` | Added capabilities registration test + invocation & error handler tests |

### New Files (3 files)
| File | Purpose |
|------|---------|
| `src/mikrus_mcp/tools/capabilities.py` | `describe_mikrus_capabilities` tool — zero-I/O, returns full tool catalog with manifests |
| `tests/unit/test_capabilities.py` | Unit tests for capabilities module |
| `tests/unit/test_validators.py` | Unit tests for write guard and command validation |

## Verification Results

### Unit Tests
```
310 passed in 2.34s
```
All passing, zero failed, zero skipped.

### Precommit Checks
| Tool | Result |
|------|--------|
| `ruff check src/ tests/` | All checks passed |
| `ruff format --check src/ tests/` | 45 files already formatted |
| `mypy src/` | Success: no issues found in 17 source files |
| `bandit -r src/ -lll` | No issues identified |

### Smoke Check
- `/health` → `{"status":"healthy","tool_count":33,"tools_version":"1.1.0"}`
- `/api/tools` → total: 33, includes `describe_mikrus_capabilities`
- `POST /api/tools/describe_mikrus_capabilities` → `success: true`, `tool_count: 33`
- Smoke test suite: 3 passed, 5 skipped (no running server)

### Error Codes
No remaining `SSH_ERROR`, `API_ERROR`, or `OPERATION_FAILED` in source files.

## Completeness Check

| Requirement | Status |
|-------------|--------|
| Write guard in 8 mutating tools | Done |
| Manage service skips guard for read-only actions | Done |
| Manage process skips guard for list action | Done |
| Command metacharacter validation | Done |
| describe_mikrus_capabilities tool | Done |
| Error codes unified to standard set | Done |
| Unit tests for new code | Done |
| tool_count: 32 → 33 in tests | Done |
| ENABLE_WRITE_OPERATIONS in .env.example | Done |
| Precommit checks pass | Done |

## Not Committed
Per instructions, no `git commit` or `git push` was executed.
