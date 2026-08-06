---
description: Security boundaries and operator obligations for privileged mikrus-mcp deployments
doc_id: system.security-model
type: system
status: active
rigor: normative
owners: [repository-maintainers]
verification: Run policy, target-binding, approval, HTTP-boundary, sanitizer, SSH, and artifact tests through `scripts/ci.py`; verify real-target TODO tests before production deployment.
---
# Security model

## Responsibility

The server exposes privileged administration capabilities for explicitly configured
mikr.us and SSH targets. It is designed for one trusted local process principal. It is not a public multi-tenant
service. Loopback Streamable HTTP authenticates one configured process principal with an
owner-only bearer token, but it does not provide public remote-user identity or tenant isolation.

## Trust boundaries

The operator controls process environment, target configuration, filesystem-mounted
secrets, principal scopes, write enablement, command-profile enablement, and approval
records. MCP arguments, upstream responses, remote file contents, logs, and errors are
untrusted.

Streamable HTTP accepts literal loopback addresses only and rejects requests without the
configured bearer token before body parsing. Deployment behind a remote proxy is unsupported until a separate profile defines TLS, authenticated principal
extraction, audience validation, per-resource authorization, proxy-header trust, and
abuse controls.

## Target identity

Each configured target has a stable public name and stable adapter identity. The
kernel authorizes the caller and target selector before lazy connection. A missing,
failed, or unavailable target returns an error; another target is never selected.

SSH verifies host identity using AsyncSSH's default `known_hosts` policy or an
explicit regular `known_hosts` file. Disabling verification requires the separate
`MCP_ALLOW_INSECURE_SSH=1` development acknowledgement and remains unsuitable for
production.

## Mutation policy

Every mutation is non-retryable and non-idempotent by default. It requires all of:

1. an active capability manifest;
2. caller capability and target scopes from process configuration;
3. `MCP_WRITE_ENABLED=true`;
4. a valid unexpired one-time approval loaded from a protected file;
5. an exact binding to principal, capability, target, and resource;
6. a deadline-bound target-resource lock.

Local arguments and target existence are validated before approval consumption. An approval
token is consumed on any approval-binding attempt. The model cannot create an
approval. Raw command execution also requires
`MCP_COMMAND_EXECUTION_ENABLED=true` and an executable allowlist.

## Filesystem and process execution

Public paths must be absolute POSIX paths. Protected read trees and protected write
trees are denied component-wise. Writes are limited to declared roots, reject a
symlink at the final target, write a private temporary file, and replace the target.

Remote filesystems can still have platform-specific rename, mount, hard-link, and
race behavior. The dedicated real-system symlink-race test must pass for each
production target class before relying on this control.

Commands assembled by public raw-command input are parsed into an argument vector,
restricted to an executable allowlist, bounded, and shell-quoted. Internal adapter
commands use validated values and fixed command templates. SSH stdout and stderr share
a byte limit and process deadline; cancellation terminates the owned process.

## Data handling

Results are minimized recursively before MCP serialization. Sensitive dictionary
keys, authorization values, tokens, passwords, API keys, and private keys are
redacted. Network addresses remain visible because they are required for diagnostics
and are controlled through capability confidentiality and scopes rather than blanket
text destruction.

Database credential retrieval is classified as credential data and bypasses the
process cache. Raw upstream response bodies are not copied into public errors.

## Failure behavior

Validation, authentication, authorization, not-found, conflict, rate-limit, timeout,
unavailable, upstream, ambiguous-outcome, cancellation, and internal failures remain
distinct. Cancellation is re-raised. Mutations are never retried after rate limiting,
timeout, disconnect, or an ambiguous outcome.

The server is ready when configuration, manifest coverage, kernel construction, and
transport construction succeed. Target connection is lazy; per-target status is
reported separately.

## Reporting vulnerabilities

Do not include credentials, private hostnames, approval tokens, or real backend output
in a public issue. Contact the repository maintainer privately with a minimized
reproduction and the affected revision.
