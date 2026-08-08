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
mikr.us and SSH targets. It is designed for one trusted local operator profile, not a
public multi-tenant service. Local stdio defaults to an effective-OS principal (`posix-uid:<uid>` on POSIX) and may use an explicitly configured service identity.
Loopback Streamable HTTP authenticates each request with the protected bearer token and
derives a request-scoped non-secret principal identifier from that credential.

## Trust boundaries

The operator controls process environment, target configuration, filesystem-mounted
secrets, stdio principal scopes, HTTP bearer credentials and scopes, write enablement,
and approval records. MCP arguments, upstream responses,
remote file contents, logs, and errors are untrusted.

Streamable HTTP accepts literal loopback addresses only and rejects requests without the
configured bearer token before body parsing. The authenticated caller is attached to the
ASGI request scope and read through the public MCP request context; HTTP authorization
does not fall back to the process-global principal. Deployment behind a remote proxy is
unsupported until a separate profile defines TLS, audience validation, proxy-header
trust, external principal extraction, per-resource authorization, and abuse controls.

## Target identity

Each configured target has a public selector alias and a stable adapter identity. The
kernel authorizes the caller and selector before lazy connection. Approval records bind
the stable adapter identity, not the alias, so changing an alias to a different server ID
or SSH endpoint invalidates previously persisted approvals. A missing, failed, or
unavailable target returns an error; another target is never selected.

After connection, the registry verifies that the client's resolved stable identity still
matches the configured stable identity. SSH verifies host identity using AsyncSSH's
default `known_hosts` policy or an explicit regular `known_hosts` file. Disabling
verification requires the separate `MCP_ALLOW_INSECURE_SSH=1` development
acknowledgement and remains unsuitable for production.

## Mutation policy

Every mutation is non-retryable and non-idempotent by default. It requires all of:

1. an active capability manifest;
2. caller capability and target scopes from the authenticated request or local stdio configuration;
3. `MCP_WRITE_ENABLED=true`;
4. a valid unexpired one-time approval loaded from a protected file;
5. an exact binding to principal, capability, stable target identity, resource, and normalized operation arguments;
6. a deadline-bound target-resource lock.

Local arguments and target existence are validated before approval matching. For a target
mutation the target is connected and its stable identity is revalidated before the
one-time approval is consumed. The model cannot create an approval. General-purpose raw command execution is not a public capability; privileged system actions are split into operation-specific tools with bounded schemas and validators.

## Filesystem and process execution

Public paths must be absolute POSIX paths. Protected read trees and protected write
trees are denied component-wise. Writes are limited to declared roots, reject a
symlink at the final target, write a private temporary file, and replace the target.

Remote filesystems can still have platform-specific rename, mount, hard-link, and
race behavior. The dedicated real-system symlink-race test must pass for each
production target class before relying on this control.

There is no public raw-command string boundary. Internal adapter commands use validated values, fixed operation-specific templates, explicit option separators where supported, and shell quoting for data values. SSH stdout and stderr share
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
unavailable, transient-upstream, upstream-rejected, upstream-protocol, ambiguous-outcome,
cancellation, and internal failures remain distinct. Only explicitly transient read failures
are eligible for manifest-controlled retry. A mutation timeout, disconnect after request
submission, or qualifying upstream 5xx is reported as `AMBIGUOUS_OUTCOME`; the caller must
reconcile target state before any new mutation attempt. Cancellation is re-raised.

The server is ready when configuration, manifest coverage, kernel construction, and
transport construction succeed. Target connection is lazy; per-target status is
reported separately.

## Release trust boundary

Release validation is separated from privileged publication. A read-only job requires the
selected full commit SHA to be reachable from the repository default branch, verifies the
exact CI release bundle, exercises the candidate image, and records the tested digest in an
isolated quarantine registry. The protected publisher receives only the validated quarantine
reference and digest. It does not checkout candidate source and does not load or execute the
candidate image; it promotes the exact digest with registry-side manifest operations and then
attests that digest. Missing quarantine configuration or digest mismatch fails closed.

## Reporting vulnerabilities

Do not include credentials, private hostnames, approval tokens, or real backend output
in a public issue. Contact the repository maintainer privately with a minimized
reproduction and the affected revision.
