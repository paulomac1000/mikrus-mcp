# Changelog

All notable changes to mikrus-mcp are recorded here.

## [2.0.0] - 2026-08-06

### Breaking

- Migrated from MCP SDK v1 `FastMCP` and legacy HTTP+SSE to MCP SDK v2,
  stdio, and stateless Streamable HTTP.
- Removed the unauthenticated production REST bridge and SDK-private lifecycle access.
- Removed automatic fallback from an unavailable default target.
- Split mixed-risk service and process tools into separate read and mutation tools.
- Changed mutations to require operator enablement, scopes, and one-time
  server-side approval records that are not exposed as MCP arguments.
- Enabled SSH host verification by default.
- Replaced silent numeric clamping and permissive write paths with fail-closed validation.

### Added

- One application-owned invocation kernel for validation, authorization, target
  binding, deadlines, concurrency, execution, errors, sanitization, and telemetry.
- Complete typed capability manifests with supported and active catalogs.
- Loopback Host, Origin, bearer authentication, and request-body controls for HTTP.
- Credential-scoped rate limiting, manifest-driven read-only retry policy, bounded HTTP
  and SSH output, field-aware minimization, and protocol-native structured results.
- A trusted local approval CLI and secure runtime reload of atomically replaced approval files.
- Canonical remote path checks for read operations and write-parent containment.
- Mocked official-client smoke tests and explicit TODO tests for real-system and
  provider-backed evidence.
- Governed architecture, security, migration, compliance, and upstream-review documents.
- SHA-pinned least-privilege CI, explicit workflow privilege-profile validation, exact
  wheel smoke, a digest-pinned base image, and release promotion of the previously tested
  CI wheelhouse and image archive without rebuilding.
- Canonical-parent file writes using unpredictable `mktemp` files and atomic `mv -T`
  replacement instead of predictable process-ID temporary paths.

### Deferred

- Complete platform-specific hashed dependency locks and provider-backed adoption approval.
- Real SSH identity enrollment, mikr.us mutation reconciliation, remote filesystem race
  testing, and multi-architecture published-image evidence.

## [1.1.1] - 2026-05-22

Corrected Docker tag documentation and publication metadata.

## [1.1.0] - 2026-05-17

Added write gating, capability introspection, manifest factories, and expanded CI checks.

## [1.0.0] - 2026-05-11

Added global client lifecycle handling, response sanitization, and AFDS integration.

## [0.2.0] - 2026-05-08

Introduced structured response wrappers, risk prefixes, and reorganized tests.

## [0.1.0] - 2026-05-01

Initial multi-target mikr.us and SSH MCP server release.
