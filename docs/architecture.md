---
description: Runtime architecture, dependency direction, lifecycle, and failure behavior of mikrus-mcp
doc_id: system.runtime-architecture
type: system
status: active
rigor: normative
owners: [repository-maintainers]
verification: Run `python scripts/core_gate.py`, inspect manifest coverage, and exercise both official-client transport suites against the exact built wheel.
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
construction. `build_server()` validates exact manifest-to-registration coverage,
constructs one kernel, and installs MCP tools, resources, prompts, and lifespan.

Targets are registered without opening network connections. A client is constructed
and connected only after local input validation, principal scope checks, exact target
selection, operator policy, and any required approval check. Successful clients are
owned by `TargetRegistry` and closed once during server shutdown.

A target connection failure is retained as target-local status. The configured
default remains the same identifier and is never replaced by another target.

## Invocation sequence

Every invocation performs these steps in order:

1. resolve an active application-owned manifest;
2. reject unknown arguments and normalize bounded local values;
3. resolve the configured target selector and target kind without network I/O;
4. authenticate the process or HTTP boundary and authorize capability and target scopes;
5. enforce operator write policy;
6. verify that a bound approval exists when required, without consuming it;
7. acquire the manifest-defined deadline-bound concurrency lock;
8. lazily open the exact target and verify its stable configured identity;
9. atomically consume one bound approval immediately before a mutation;
10. execute the adapter once; for proven idempotent reads only, the kernel applies the
    manifest retry conditions and bounded backoff;
11. classify failures, minimize output, enforce the response byte limit, and emit metadata.

A lock timeout, target connection failure, or binding mismatch does not consume an
approval. Mutations are not automatically retried after rate limits, disconnects,
timeouts, or ambiguous outcomes. For mikr.us mutations, post-submission timeout/disconnect
and qualifying 5xx outcomes are classified as ambiguous and require state reconciliation.
Reads distinguish transient transport/5xx failures from rejected or protocol-invalid
responses; only the transient class can satisfy manifest retry conditions. Adapters
perform one request attempt; manifests and the kernel are the only retry-policy source.

## Public components

The supported catalog contains a complete manifest for every public tool. General-purpose raw command execution is intentionally absent; privileged actions are represented by operation-specific capabilities. Introspection exposes the catalog without target I/O.

Mixed-risk operations are split. Service inspection and mutation use different tools,
as do process listing and termination. This keeps one manifest and one schema aligned
with each operation.

## Transports

Stdio is the local subprocess transport and reserves stdout for protocol messages.
Streamable HTTP is stateless, loopback-only, bearer-authenticated, Host-validated,
Origin-validated, and request-body bounded. Both transports use the same server
registration and invocation kernel. Legacy HTTP+SSE and the former test REST bridge
are not supported.

## Failure modes

Configuration, manifest coverage, transport construction, and secret-file validation
fail startup. Target failures do not make other target identities interchangeable.
Validation, authentication, authorization, not-found, conflict, rate-limit, timeout,
unavailable, upstream, ambiguous-outcome, cancellation, and internal categories stay
distinct. Cancellation propagates after owned process termination.

Readiness means process configuration and application composition are valid. It does
not claim every optional target is connected or healthy; target status is reported
separately.

## Observability

Each result contains a generated request ID, bounded duration, and the exact target
identifier when applicable. Logs go to stderr and public failures do not contain raw
upstream bodies or credentials. Production SLOs, metrics export, durable audit storage,
and distributed tracing remain deployment-profile responsibilities recorded in the
compliance status.
