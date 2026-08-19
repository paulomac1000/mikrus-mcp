---
afds_schema_version: 2
description: Breaking migration procedure from mikrus-mcp 1.x to the hardened 2.0 architecture
doc_id: workflow.version-two-migration
type: workflow
status: active
rigor: operational
owners: [repository-maintainers]
verification:
  kind: command
  value: Complete the checklist against a disposable target, run `scripts/ci.py`, and verify official-client stdio and Streamable HTTP evidence for the exact built artifact.
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
- Tools return protocol-native structured results and provenance metadata; failures use MCP tool errors with retry guidance.
- A failed default target no longer falls back to another target.
- SSH host-key verification defaults to enabled; mutation approvals bind the verified host-key fingerprint, not only `user@host:port`.
- Insecure SSH can be acknowledged only for read-only use; enabling writes with host-key verification disabled fails startup.
- Mutations require process scopes, write enablement, and one-time approval records.
- Supported capabilities and runtime-active capabilities are distinct; inactive capabilities expose a reason in the catalog and are not registered as tools.
- `manage_service` is replaced by `get_service_status` and `change_service_state`.
- `manage_process` is replaced by `list_processes` and `terminate_process`.
- General-purpose raw command execution is not exposed; privileged system actions use operation-specific tools and validation.
- Out-of-range line and time parameters fail instead of being silently clamped.
- Remote file writes use component-safe no-follow directory descriptors and require Python 3 on the target.
- The default operation deadline is 120 seconds and is independently capped by `MCP_SERVER_MAX_DEADLINE_MS`.

## Migration steps

1. Upgrade the runtime to Python 3.12 or newer.
2. Rebuild the environment from the committed hashed lock matching the supported Python lane; do not reuse an editable 1.x site package.
3. Replace `MCP_PORT`-driven SSE configuration with `MCP_TRANSPORT=streamable-http` or retain stdio.
4. Keep HTTP binding on a literal loopback address and configure `MCP_HTTP_BEARER_TOKEN_FILE` with mode `0600`.
5. Add a verified SSH host fingerprint to the selected `known_hosts` file.
6. Review process scopes and narrow `MCP_ALLOWED_SCOPES` to the required tools and targets.
7. Keep writes disabled and execute all read workflows on disposable targets.
8. Prepare an owner-only approval file outside the repository.
9. For an SSH mutation, run `scripts/approval.py` while the intended target is reachable so the approval is bound to the verified peer fingerprint.
10. Enable one mutation at a time, execute it once, and verify its postcondition.
11. Run the real-system TODO tests for each deployed backend and platform, including the remote filesystem race case.
12. Build the wheel once, test that exact wheel, build the image from it, and retain the wheel digest and image digest.

## Validation

```bash
.venv/bin/python scripts/core_gate.py
.venv/bin/python scripts/ci.py
.venv/bin/python -m build --wheel
.venv/bin/python scripts/artifact_smoke.py \
  --wheel dist/mikrus_mcp-2.0.0-py3-none-any.whl \
  --wheelhouse wheelhouse
```

Verify that tool discovery contains no legacy mixed-risk names, does not expose
`execute_command`, and omits capabilities which are inactive for the configured backend
or current write policy. Inspect `capabilities://catalog` for the corresponding inactive
reasons.

## Rollback

Disable writes first. Stop the 2.0 process, restore the previous immutable wheel or
image digest, and restore the previous client configuration. Do not restore legacy
public SSE exposure, selector-only SSH approvals, or target fallback as an emergency
shortcut.

## Residual evidence

Provider-backed cross-platform artifact checks, real SSH fingerprint enrollment and
rotation behavior, real mikr.us mutation reconciliation, and remote filesystem race
tests remain deployment acceptance requirements. Their placeholders are in
`tests/real_system/`. Independent production approval remains separate from structural
self-assessment and provider CI.
