# Mikrus MCP Server

A security-focused Model Context Protocol server for explicitly configured mikr.us API and SSH targets.
The runtime uses one application-owned invocation kernel for target binding, authorization, approvals,
timeouts, concurrency, redaction, and structured failures.

## Supported transports

- `stdio` is the default local transport.
- Streamable HTTP is restricted to literal loopback addresses and requires a protected bearer-token file.
- Legacy HTTP+SSE and the unauthenticated REST bridge are not used by the production entrypoint.

## Security defaults

- An unavailable target never falls back to another configured target.
- SSH host-key verification is enabled by default.
- Mutations are disabled unless `MCP_WRITE_ENABLED=true` and require a one-time approval bound to the principal, capability, stable target identity, resource, and normalized operation arguments.
- Mutations are not automatically retried after timeout, disconnect, rate limiting, or ambiguous completion.
- Capability manifests must cover every registered tool or startup fails.
- General-purpose raw command execution is not exposed. Privileged system operations are separate capabilities with operation-specific validation.

Read [SECURITY.md](SECURITY.md) before enabling writes.

## Local development

```bash
python3 -m venv .venv
.venv/bin/python -m pip install "pip==26.1.2"
.venv/bin/python -m pip install ".[dev]"
.venv/bin/python scripts/core_gate.py
```

The complete hosted gate additionally runs formatting, linting, type checking, dependency and security audits,
AFDS validation, official MCP client tests, exact-wheel stdio and Streamable HTTP smoke tests, and the container lane.

## Minimal mikr.us configuration

```bash
export MIKRUS_API_KEY='replace-me'
export MIKRUS_SERVER_NAME='srv-id'
.venv/bin/python -m mikrus_mcp
```

For multiple targets, set `MCP_SERVERS` to a JSON object and preserve the exact target identifier in tool calls.
Operator approvals are issued with `scripts/approval.py --server <configured-alias>`; the CLI resolves that alias to the target's stable adapter identity before persisting the approval.

## Streamable HTTP

```bash
umask 077
python -c 'import secrets; print(secrets.token_urlsafe(48))' > .mcp-http-token
export MCP_TRANSPORT=streamable-http
export MCP_HOST=127.0.0.1
export MCP_PORT=8000
export MCP_HTTP_BEARER_TOKEN_FILE="$PWD/.mcp-http-token"
.venv/bin/python -m mikrus_mcp
```

Clients connect to `http://127.0.0.1:8000/mcp` with `Authorization: Bearer <token>`.
Each authenticated HTTP request receives a request-scoped principal derived as a SHA-256 identifier of the bearer credential; the raw bearer token is never used as the principal value. Stdio derives its default principal from the effective OS identity (`posix-uid:<uid>` on POSIX); `MCP_PRINCIPAL` may explicitly name a service identity. Process-global identity is not used to authorize Streamable HTTP requests.
Remote proxy deployment is outside the supported security profile.

## Release promotion

Container release promotion is fail-closed. The read-only validation job selects a full
40-character release SHA reachable from the repository default branch, verifies the exact
CI bundle, exercises the candidate outside the protected publisher, and pushes the tested
digest to an isolated quarantine registry. The protected `release` environment then promotes
that exact digest with `docker buildx imagetools create`; it does not checkout candidate
source, load the candidate image, or execute candidate code.

Configure `QUARANTINE_REGISTRY` and `QUARANTINE_REPOSITORY` as repository variables plus
write/read quarantine credentials as release secrets before using `publish.yml`. A manual release selected by full commit SHA publishes only the immutable `sha-<40>` tag; the stable version tag is emitted only when the selected release identity is an existing matching `v<version>` tag.

The reviewed container profile is stdio-only. Streamable HTTP is an application transport but is not advertised as a host-published container profile.

See [MIGRATION.md](MIGRATION.md), [docs/architecture.md](docs/architecture.md), and
[docs/compliance-status.md](docs/compliance-status.md) for migration details, evidence, and residual risks.
