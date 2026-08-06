---
description: Breaking migration procedure from mikrus-mcp 1.x to the hardened 2.0 architecture
doc_id: workflow.version-two-migration
type: workflow
status: active
rigor: operational
owners: [repository-maintainers]
verification: Complete the checklist against a disposable target, run `scripts/ci.py`, and verify official-client stdio and Streamable HTTP evidence for the exact built artifact.
---
# Migrate from version 1.x to 2.0

## Preconditions

Use a work branch, disposable targets, a protected approval file, and a rollback copy
of the previous image or wheel. Do not test mutations against production during the
first migration pass.

## Breaking changes

- The runtime uses the official MCP Python SDK v2 and Python 3.12 or newer.
- Legacy two-endpoint HTTP+SSE and the unauthenticated REST bridge are removed.
- Streamable HTTP is stateless, loopback-only, and bearer-authenticated from an owner-only token file.
- Tools return protocol-native structured results; failures use MCP tool errors.
- A failed default target no longer falls back to another target.
- SSH host-key verification defaults to enabled.
- Mutations require process scopes, write enablement, and one-time approval records.
- `manage_service` is replaced by `get_service_status` and `change_service_state`.
- `manage_process` is replaced by `list_processes` and `terminate_process`.
- Raw command execution is disabled unless its separate profile is enabled.
- Out-of-range line and time parameters fail instead of being silently clamped.
- File writes outside safe roots fail instead of producing a warning.

## Migration steps

1. Upgrade the runtime to Python 3.12 or newer.
2. Rebuild the environment from `pyproject.toml`; do not reuse an editable 1.x site
   package.
3. Replace `MCP_PORT`-driven SSE configuration with `MCP_TRANSPORT=streamable-http`
   or retain stdio.
4. Keep HTTP binding on a literal loopback address and configure `MCP_HTTP_BEARER_TOKEN_FILE` with mode `0600`.
5. Add a verified SSH host fingerprint to the selected `known_hosts` file.
6. Review process scopes and narrow `MCP_ALLOWED_SCOPES` to the required tools and
   targets.
7. Keep writes disabled and execute all read workflows on disposable targets.
8. Prepare an owner-only approval file outside the repository.
9. Enable one mutation at a time, execute it once, and verify its postcondition.
10. Run the real-system TODO tests for each deployed backend and platform.
11. Build the wheel once, test that exact wheel, build the image from it, and retain
    the wheel digest and image digest.

## Validation

```bash
.venv/bin/python scripts/core_gate.py
.venv/bin/python scripts/ci.py
.venv/bin/python -m build --wheel
.venv/bin/python scripts/artifact_smoke.py \
  --wheel dist/mikrus_mcp-2.0.0-py3-none-any.whl \
  --wheelhouse wheelhouse
```

Verify that tool discovery contains no legacy mixed-risk names and no command tool
unless its profile is enabled.

## Rollback

Disable write and command profiles first. Stop the 2.0 process, restore the previous
immutable wheel or image digest, and restore the previous client configuration. Do
not restore legacy public SSE exposure or target fallback as an emergency shortcut.

## Residual evidence

Provider-backed cross-platform artifact checks, real SSH identity enrollment, real
mikr.us mutation reconciliation, and remote filesystem race tests remain deployment
acceptance requirements. Their placeholders are in `tests/real_system/`.
