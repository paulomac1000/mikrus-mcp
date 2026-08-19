---
afds_schema_version: 2
description: Runtime architecture, dependency direction, lifecycle, and failure behavior of mikrus-mcp
doc_id: system.runtime-architecture
type: system
status: active
rigor: normative
owners: [repository-maintainers]
verification:
  kind: command
  value: Run `python scripts/core_gate.py`, inspect supported and active manifest coverage, and exercise both official-client transport suites against the exact built wheel.
---
# Runtime architecture

## Responsibility

`mikrus-mcp` exposes governed MCP capabilities for explicitly configured mikr.us and
SSH targets. It keeps MCP transport code, application policy, target lifecycle, and
backend adapters separate so every invocation follows one fail-closed path.

## Dependency direction

The dependency direction is:

```text
MCP registration and HTTP middleware
              |
              v
       InvocationKernel
       /      |       \
 manifests  policy  TargetRegistry
                       |
                       v
              mikr.us / SSH clients
```

Backend clients do not import MCP SDK types. Transport wrappers do not call clients
directly. `InvocationKernel.invoke()` is the only application operation entry point.

## Composition and lifecycle

`load_settings()` loads and validates one immutable process snapshot before server
construction. `build_server()` validates exact active-manifest-to-registration coverage,
constructs one kernel, and installs MCP tools, resources, prompts, and lifespan.

The supported catalog contains every application-owned capability. Runtime activation is
derived from backend availability requirements and process write policy. A supported but
inactive capability remains visible in `capabilities://catalog` with an explicit inactive
reason but is not registered as a public tool.

Targets are registered without opening network connections. A client is constructed and
connected only after local input validation, principal scope checks, exact target
selection, and operator write policy. For an approval-protected target mutation, the exact
backend is connected before approval matching so the approval can be bound to the resolved
backend identity. Successful clients are owned by `TargetRegistry` and closed once during
server shutdown.

A target connection failure is retained as target-local status. The configured default
remains the same identifier and is never replaced by another target.

## Invocation sequence

Every invocation performs these steps in order:

1. resolve an active application-owned manifest;
2. reject unknown arguments and normalize bounded local values;
3. resolve the configured target selector and target kind without fallback;
4. authenticate the process or HTTP boundary and authorize capability and target scopes;
5. enforce operator write policy;
6. for approval-protected target mutations, open the exact target and resolve the stable backend identity;
7. verify that an approval bound to principal, capability, resolved target identity, resource, and normalized arguments exists without consuming it;
8. validate the request deadline against the independent server maximum and acquire the manifest-defined concurrency lock;
9. atomically consume one bound approval immediately before a mutation;
10. execute the adapter once; for proven idempotent reads only, the kernel applies the manifest retry conditions and bounded backoff;
11. classify failures, minimize output, attach provenance, enforce the serialized application-envelope byte limit, and return the result.

A lock timeout, target connection failure, or binding mismatch does not consume an
approval. Mutations are not automatically retried after rate limits, disconnects,
timeouts, or ambiguous outcomes. For mikr.us mutations, post-submission timeout/disconnect
and qualifying 5xx outcomes are classified as ambiguous and require state reconciliation.
Reads distinguish transient transport/5xx failures from rejected or protocol-invalid
responses; only the transient class can satisfy manifest retry conditions. Adapters
perform one request attempt; manifests and the kernel are the only retry-policy source.

## Target identity

The configured mikr.us server ID is its stable backend identity. SSH has two identities:
the configured selector (`user@host:port`) and the resolved peer identity. After host-key
verification, the resolved identity appends the SHA-256 host-key fingerprint. Approval
records for SSH mutations bind the resolved peer identity. Cached SSH clients are reused
only while the connection remains open; reconnecting re-resolves the peer identity.

## Filesystem writes

Remote file mutation uses a fixed operation-specific Python helper rather than a shell
check followed by a path-based rename. The helper traverses allowed absolute roots with
directory-relative `open()` calls using `O_DIRECTORY` and `O_NOFOLLOW`, rejects an
existing non-regular or symlink leaf, writes an exclusive private temporary file, fsyncs
it, and performs a directory-relative atomic replace. The same primitive is used by SSH
and the mikr.us `/exec` backend. Real target classes still require the dedicated
filesystem-race acceptance test.

## Transports

Stdio is the local subprocess transport and reserves stdout for protocol messages.
Streamable HTTP is stateless, loopback-only, bearer-authenticated, Host-validated,
Origin-validated, and request-body bounded. Both transports use the same server
registration and invocation kernel. Legacy HTTP+SSE and the former test REST bridge are
not supported.

## Failure modes and deadlines

Configuration, active manifest coverage, transport construction, and secret-file
validation fail startup. Target failures do not make other target identities
interchangeable. Validation, authentication, authorization, not-found, conflict,
rate-limit, timeout, unavailable, transient-upstream, upstream-rejected,
upstream-protocol, ambiguous-outcome, cancellation, and internal categories stay
distinct. Cancellation propagates after owned process termination.

Capability timeout, caller/request deadline, and server maximum deadline are distinct.
The effective deadline is the minimum of those three values. The default and server
maximum are 120 seconds, so long bounded capabilities are not silently truncated by the
old 10-second process default.

## Health model

`health://ready` reports startup completion, liveness, readiness, dependency state,
capability degradation, and shutdown ownership separately. Target connection is lazy:
`not_connected` does not itself make the process unready. A recorded unavailable default
target makes readiness false. Inactive capabilities are listed with their reasons so
operator policy degradation is not confused with a missing implementation.

## Observability and response contract

Each successful result contains a generated request ID, capability and application
version, source artifact identity, bounded duration, target selector, resolved target
identity, and backend kind when applicable. The same request metadata accompanies error
responses. Public MCP errors preserve retryability and `retry_after_seconds` guidance.
Response byte limits apply after the application envelope and provenance metadata are
serialized, not only to the nested data value. Logs go to stderr and public failures do
not contain raw upstream bodies or credentials.

Production SLOs, metrics export, durable audit storage, and distributed tracing remain
deployment-profile responsibilities recorded in the compliance status.
