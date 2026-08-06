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
- Mutations are disabled unless `MCP_WRITE_ENABLED=true` and require a one-time approval bound to the principal, capability, target, and resource.
- Mutations are not automatically retried after timeout, disconnect, rate limiting, or ambiguous completion.
- Capability manifests must cover every registered tool or startup fails.
- Raw command execution is absent from the default catalog. Its compatibility profile is disabled unless the operator explicitly enables it and supplies an executable allowlist.

Read [SECURITY.md](SECURITY.md) before enabling writes or the command compatibility profile.

## Local development

```bash
python3 -m venv .venv
.venv/bin/python -m pip install "pip==25.2"
.venv/bin/python -m pip install ".[dev]"
.venv/bin/python scripts/core_gate.py
```

The complete hosted gate additionally runs formatting, linting, type checking, dependency and security audits,
AFDS validation, official MCP client tests, exact-wheel smoke tests, and the container lane.

## Minimal mikr.us configuration

```bash
export MIKRUS_API_KEY='replace-me'
export MIKRUS_SERVER_NAME='srv-id'
.venv/bin/python -m mikrus_mcp
```

For multiple targets, set `MCP_SERVERS` to a JSON object and preserve the exact target identifier in tool calls.

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
Remote proxy deployment is outside the supported security profile.

See [MIGRATION.md](MIGRATION.md), [docs/architecture.md](docs/architecture.md), and
[docs/compliance-status.md](docs/compliance-status.md) for migration details, evidence, and residual risks.
