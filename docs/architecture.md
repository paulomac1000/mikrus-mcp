---
description: Runtime architecture, dependency boundaries, and invocation flow for mikrus-mcp
doc_id: system.runtime-architecture
type: system
status: active
rigor: operational
owners: [repository-maintainers]
verification: Run python scripts/core_gate.py and tests/unit/test_kernel.py, tests/unit/test_server_registration.py, and tests/smoke/test_official_client.py.
---
# Runtime architecture

## Responsibility

The service exposes bounded VPS administration capabilities over the official MCP Python SDK v2. It supports stdio for local subprocess integration and stateless Streamable HTTP on literal loopback addresses.

## Boundaries

`config.py` owns one typed immutable settings snapshot. `manifests.py` owns capability safety metadata. `targets.py` owns exact target configuration, lazy client creation, stable identity checks, and cleanup. `client.py` contains HTTP and SSH adapters without MCP types. `kernel.py` is the only policy and execution path. `tool_*.py` contains typed MCP callables that translate arguments and results without duplicating policy. `server.py` is the composition root and transport owner.

Domain/adaptor code must not import MCP transport types. Transport adapters must not invoke clients directly or monkey-patch SDK context. Application modules must not create clients or load secrets at import time.

## Invocation flow

1. Resolve the application-owned manifest and active profile.
2. Validate and normalize local arguments and the declared target selector.
3. Authenticate the process-bound principal.
4. Authorize capability scopes and the exact target namespace.
5. Resolve the configured target without fallback and verify stable identity.
6. Enforce write/command policy and consume a bound one-time approval when required.
7. Apply deadline and keyed concurrency controls.
8. Invoke one adapter operation.
9. Map validation, authorization, rate-limit, timeout, unavailable, upstream, and internal errors.
10. Minimize and sanitize structured output and attach request telemetry.

## Lifecycle

The MCP server lifespan owns the kernel and target registry. Target clients are constructed lazily after authorization, reused inside their owner scope, and closed once at shutdown. Optional target failure remains isolated and visible through discovery. An all-target failure does not make another target the default.

## Interfaces

The public capability catalog is available as the `describe_mikrus_capabilities` tool and `capabilities://catalog` resource. Readiness is available as `health://ready`; it reports configuration and active catalog state, not upstream health proof.

## Failure modes

Configuration validation fails before listener or client construction. Unknown/inactive capabilities and targets fail closed. Mutations are never automatically retried. Cancellation is re-raised after bounded application cleanup. Unexpected exceptions are logged without protected payloads and returned as a generic internal tool error.

## Observability

Every result contains a generated request ID, duration, and target where applicable. Logs go to stderr and do not include credentials. Production deployments should add structured metrics and traces at the external host boundary without weakening redaction or principal binding.
