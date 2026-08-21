---
afds_schema_version: 2
description: Security boundaries and operator obligations for privileged mikrus-mcp deployments
doc_id: system.security-model
type: system
status: active
rigor: normative
owners: [repository-maintainers]
verification:
  kind: command
  value: Run policy, target-binding, approval, HTTP-boundary, sanitizer, SSH, filesystem-race, and artifact tests through `scripts/ci.py`; verify real-target TODO tests before production deployment.
---
# Security model

## Responsibility

The server exposes privileged administration capabilities for explicitly configured
mikr.us and SSH targets. It is designed for one trusted local operator profile, not a
public multi-tenant service. Local stdio defaults to an effective-OS principal
(`posix-uid:<uid>` on POSIX) and may use an explicitly configured service identity.
Loopback Streamable HTTP authenticates each request with the protected bearer token and
derives a request-scoped non-secret principal identifier from that credential.

## Trust boundaries

The operator controls process environment, target configuration, filesystem-mounted
secrets, stdio principal scopes, HTTP bearer credentials and scopes, write enablement,
and approval records. MCP arguments, upstream responses, remote file contents, logs,
and errors are untrusted.

Streamable HTTP accepts literal loopback addresses only and rejects requests without the
configured bearer token before body parsing. The authenticated caller is attached to the
ASGI request scope and read through the public MCP request context; HTTP authorization
does not fall back to the process-global principal. Deployment behind a remote proxy is
unsupported until a separate profile defines TLS, audience validation, proxy-header
trust, external principal extraction, per-resource authorization, and abuse controls.

## Authorization scopes and target identity

Authorization is deliberately two-phase. The kernel first authenticates the caller and
checks the capability (`tool:`), lexical target selector (`target:`), and manifest data
classification (`data:`) before target configuration is inspected or network-backed
resolution starts. After the backend is connected, the kernel authorizes the exact stable
identity (`target-id:`) and, for capabilities with a resource argument, a deterministic
resource scope (`resource:`) derived from capability name and the normalized resource.
A missing, failed, unavailable, or unauthorized target never causes fallback to another
target.

The default single-operator profile explicitly grants `tool:*`, `target:*`, `target-id:*`,
`resource:*`, and `data:*`. Operators overriding `MCP_ALLOWED_SCOPES` must grant the new
resolved axes deliberately; an old `tool:*,target:*` override now fails closed rather than
silently bypassing post-resolution authorization.

For mikr.us, the stable identity is the configured server ID. For SSH, the configured
selector identity (`user@host:port`) is not sufficient. After AsyncSSH successfully
verifies the host against its default `known_hosts` policy or an explicit regular
`known_hosts` file, the client derives the stable identity from the selector plus the
verified SHA-256 host-key fingerprint. The kernel validates that resolved identity against
the target configuration and requires matching `target-id:` authorization before any
backend operation. The trusted approval CLI resolves the peer identity before persisting
an SSH mutation approval, and the kernel resolves it again before approval matching and
consumption.

`MCP_ALLOW_INSECURE_SSH=1` is a development acknowledgement for read-only SSH use. An
SSH target with host-key verification disabled cannot be used while writes are enabled.

## Mutation policy

Every mutation is non-retryable and non-idempotent by default. It requires all of:

1. an active capability manifest;
2. authenticated capability, selector, data-classification, resolved-target, and resource authorization;
3. `MCP_WRITE_ENABLED=true`;
4. a valid unexpired one-time approval loaded from a protected file;
5. an exact binding to principal, capability, resolved stable target identity, resource, and normalized operation arguments;
6. a deadline-bound target-resource lock.

Local arguments and lexical selector authorization happen before protected target I/O.
For a target mutation the exact target is connected, the stable backend identity and
resource authorization are checked, and only then is the matching approval checked. The
one-time record is consumed inside the operation lock immediately before mutation
execution, after the cached resolved identity is revalidated. The model cannot create an
approval. General-purpose raw command execution is not a public capability; privileged
system actions are split into operation-specific tools with bounded schemas and validators.

## Filesystem and process execution

Public paths must be absolute POSIX paths. Protected read trees and protected write
trees are denied component-wise. Remote writes are restricted to declared roots and use
a fixed Python helper on the target which opens every directory component relative to a
held directory descriptor with `O_DIRECTORY` and `O_NOFOLLOW`, rejects an existing final
symlink or non-regular file, writes a private exclusive temporary file, fsyncs it, and
replaces the target with directory-relative `os.replace()`. This removes the previous
check-then-use path re-resolution between containment validation and replacement.

A production target therefore needs Python 3 with the required POSIX dir-fd primitives.
The dedicated real-system symlink-race test remains required because mount, network
filesystem, hard-link, and platform semantics cannot be proven by local mocks alone.

There is no public raw-command string boundary. Internal adapter commands use validated
values, fixed operation-specific templates, explicit option separators where supported,
and shell quoting for data values. SSH stdout and stderr share a byte limit and process
deadline. Timeout, cancellation, and output-overflow paths terminate the owned process,
wait for a bounded interval, escalate by closing the channel, and preserve the original
operation classification rather than exposing cleanup failures.

## Data handling

Results are minimized recursively before MCP serialization. Sensitive dictionary keys,
authorization values, tokens, passwords, API keys, and private keys are redacted.
Network addresses remain visible because they are required for diagnostics and are
controlled through capability confidentiality and scopes rather than blanket text
destruction.

Database credential retrieval is classified as credential data and bypasses the process
cache. Raw upstream response bodies are not copied into public errors. Successful MCP
results preserve request/capability/artifact/target provenance metadata. Error payloads
preserve the same provenance only after it has been established by the reached
authorization/resolution phase; pre-resolution denials do not reveal backend details.
Retryability and `retry_after_seconds` guidance remain structured. Response limits apply
to the serialized application envelope, including metadata, rather than only to the data
field.

## Failure behavior

Validation, authentication, authorization, not-found, conflict, rate-limit, timeout,
unavailable, transient-upstream, upstream-rejected, upstream-protocol, ambiguous-outcome,
cancellation, and internal failures remain distinct. Only explicitly transient read
failures are eligible for manifest-controlled retry. Retry delay must fit the remaining
operation deadline; otherwise the original retryable error and guidance are returned. A
mutation timeout, disconnect after request submission, or qualifying upstream 5xx is
reported as `AMBIGUOUS_OUTCOME`; the caller must reconcile target state before any new
mutation attempt. Cancellation is re-raised.

Startup, liveness, readiness, target dependency state, and capability degradation are
reported separately. Target connection is lazy at startup, but the configured default is
a mandatory readiness dependency: both `not_connected` and `unavailable` make readiness
false. The supported catalog includes inactive capabilities with an explicit reason;
public tool registration contains only the active catalog for the current configuration
and write policy.

## Release trust boundary

Release validation is separated from privileged publication. A read-only job requires the
selected full commit SHA to be reachable from the repository default branch, verifies the
exact CI release bundle, exercises the candidate image, and records the tested digest in an
isolated quarantine registry. The protected publisher receives only the validated
quarantine reference and digest. It does not checkout candidate source and does not load or
execute the candidate image; it promotes the exact digest with registry-side manifest
operations and then attests that digest. Missing quarantine configuration or digest
mismatch fails closed.

The container build receives the SHA-256 digest of the application wheel from the verified
CI bundle and checks the wheel bytes again before installation. Runtime and development
dependency graphs used by CI are selected from committed hashed platform locks rather than
from an unconstrained resolver; regeneration lanes fail when a generated lock drifts from
the committed copy.

## Reporting vulnerabilities

Do not include credentials, private hostnames, approval tokens, or real backend output in
a public issue. Contact the repository maintainer privately with a minimized reproduction
and the affected revision.
