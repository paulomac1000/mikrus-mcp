# Changelog

All notable changes to mikrus-mcp are recorded here.

## [2.1.0] - 2026-09-08

### Added

- Typed SSH program execution with structured `executable`, `argv`, `cwd`, and
  `stdin` inputs; arbitrary shell strings remain unavailable on the public MCP surface.
- Bounded process-job handles with owner-scoped status, result, cancellation, and
  process-local retention semantics.
- Regression coverage for HTML-escaped mikr.us diagnostics and truthful disk-analysis failures.
- Bounded structured process snapshots with partial-state reporting and secret redaction.
- Immutable build provenance: the exact wheel is stamped at build time with the
  candidate source revision, build ID, policy revision, and package content digest;
  runtime reports `packageIntegrity` (verified/failed/unstamped), a process-local
  `instanceGeneration`, and deployment binding (verified/missing/invalid) validated
  against a deployment receipt. Environment variables can no longer establish
  artifact identity.

## [2.0.0] - 2026-08-21

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
- Canonical capability manifests projected onto the AI Skills
  `capability-manifest` contract and validated at startup and in CI.
- Governed documents migrated to AFDS document schema 2 with typed verification,
  validated by the pinned authority's AFDS validator.
- An AI Skills consumer skills lock (per-skill versions, revisions, normative
  entrypoints) pinned to the hardened authority revision and validated in CI.
- Platform-exact hashed dependency locks for Linux x64 Python 3.12/3.13/3.14 with a
  lock renderer, CI lock-evidence jobs, and drift failure on committed locks.
- Separate request and server deadlines with an explicit server deadline cap, and
  fail-fast credential throttling that returns retry guidance without consuming
  operation deadlines.
- SSH mutation approvals bound to the verified host-key peer identity in addition to
  the configured selector.
- No-follow descriptor-based directory traversal for remote writes with atomic commit
  and symlink-swap resistance.
- A real-system live instance test suite (skippable without credentials) and
  mikr.us fixtures matching real API response shapes, with full tool-surface and
  adapter execution coverage.

### Deferred

- Provider-backed adoption approval, real-system deployment evidence (SSH host-key
  rotation, controlled mutation reconciliation), and multi-architecture container
  publication beyond Linux amd64.
- Real SSH identity enrollment, mikr.us mutation reconciliation, remote filesystem race
  testing, and multi-architecture published-image evidence.
- `migration-assessment.yaml` remains intentionally absent until an independent reviewer
  can bind a schema-valid assessment to the exact reviewed revision.

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
