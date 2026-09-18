# Changelog

All notable changes to mikrus-mcp are recorded here.

## [Unreleased]

### Fixed

- Legacy flat-layout durable jobs (pre-trie `<root>/<job-id>` directories)
  are now reclaimed by a hard-bounded sweep: each GC invocation consumes at
  most `max(64, 4 × max_entries)` raw root `getdents64` entries with O(1)
  memory — no full-corpus list, sort, or on-disk migration index — and
  resumes across helper restarts through a 0600, `O_NOFOLLOW`,
  atomically-replaced `.gc-legacy-cursor` file holding the last consumed
  kernel `d_off`. The helper prefers libc's architecture-neutral wrapper,
  uses an explicit Linux ABI syscall fallback (including x86, ARM, PowerPC,
  s390, SPARC, Alpha, m68k, SH, PA-RISC, Xtensa, asm-generic families, MIPS
  ABI variants and legacy IA-64) only when necessary, and sizes
  each raw read from the remaining entry budget so every returned dirent is
  counted inside the hard cap. Stable corpora are eventually traversed over
  successive bounded passes; EOF clears the cursor so rolling-upgrade writes
  stay visible; the obsolete
  `.gc-legacy-index` internal file is removed on first touch without
  following symlinks. Wrong-type canonical cursor directories are left
  untouched while an owner-only recovery cursor preserves progress; cursor
  reads are nonblocking and require a regular opened inode so FIFOs/devices
  cannot stall GC; hard-linked lock files are rejected without chmod/mutation.
  #29

### Changed

- Dependency-lock policy split into two lanes: ordinary candidate CI installs
  and validates the committed platform-exact hash locks and never re-resolves
  dependencies (`lock-evidence` re-resolution job removed;
  `scripts/check_lock_policy.py` enforces the policy without network I/O).
  Deliberate dependency refresh moves to the scheduled/manual
  `dependency-refresh.yml` lane with pinned resolver tooling, a fresh isolated
  cache, all three Python variants, and reviewable lock diffs — nothing is
  committed automatically. Documented pip toolchain unified on 26.2.1
  (AGENTS.md/README.md previously said 26.1.2 while CI said 26.2.1). #30
- Release initiation converged on one canonical path: the stale v2.0.0-only
  `release-v2-tag.yml` workflow is removed; an operator creates or selects an
  exact `vX.Y.Z` tag and the generic `publish.yml` validates
  tag/version/SHA against `pyproject.toml`, requires a green CI release bundle
  for the exact SHA, and publishes idempotently. #31
- Release trust boundary enforced mechanically (SECURITY.md model): the
  unprivileged validation stage loads, smokes, and pushes the candidate to a
  quarantine registry and records the immutable digest; the protected
  publisher promotes that exact digest registry-to-registry over the OCI
  Distribution API via `scripts/promote_digest.py` (bundled in the
  digest-checked CI release bundle), verifies every production tag resolves
  to the promoted digest before attestation, and has no candidate checkout
  and never runs `docker load`/`docker run`/`docker build`. A
  disposable-registry regression (registry pinned by digest) proves validated
  digest == promoted digest, idempotent re-promotion, and substituted-digest
  rejection. #32
- Exact-candidate evidence rebinding automated via
  `scripts/rebind_evidence.py`: verifies the exact candidate, optionally
  requires a successful provider CI run for that SHA, and atomically rewrites
  only the `assessed_revision` binding. `--verify-only` lets release tooling
  fail closed on stale or drifted bindings; squash/integration revisions
  explicitly require fresh provider evidence. `docs/ci-troubleshooting.md`
  now documents the canonical workflow and no longer suggests weakening
  exact-candidate freshness. #33

### Fixed

- Remote durable-job storage is bounded across the full lifecycle (#29):
  worker stdout/stderr are drained through parent-owned pipes and capped per
  stream (`MAX_REMOTE_OUTPUT_BYTES`, clamped 4 KiB–16 MiB); beyond the bound
  bytes are counted (`stdoutDiscardedBytes`/`stderrDiscardedBytes`) and the
  record carries `outputCapped` plus per-stream truncation markers while the
  process runs to normal completion, and stored bytes never exceed the
  documented limit. `remote_job_output` performs a true bounded seek/read
  (a 64 KiB slice of a multi-megabyte stream reads only that slice) with
  deterministic `offset`/`nextOffset`/`eof` continuation. A bounded, idempotent
  retention GC runs after every successful `remote_job_start`: terminal job
  directories are removed after the retention horizon, orphaned/partial
  directories and dead-identity records are collected after a grace period,
  running jobs with live identities are never removed, symlinks are never
  followed, the managed root is never escaped, and scans are capped at 256
  entries. GC failures surface as a typed `gc` error without failing the
  start, and expired jobs keep machine-readable tombstones
  (`remotePayloadRemoved`) after payload bytes are removed. #29

## [2.2.0] - 2026-09-16

### Changed

- Typed SSH program execution admission is now a per-executable policy:
  `docker` (read-only subcommands), `curl` (diagnostic allowlist only — leading
  `-q`/`--disable` required, GET/HEAD only, no request bodies/uploads, no
  config files (`-K/--config`), no `-H @file/@-`, no proxy/Unix-socket/trace/
  dump/cookie/etag file I/O, `-o` restricted to `/dev/null`, explicit
  `http://`/`https://` destinations only, loopback/private/link-local/metadata/
  local hosts rejected, optional fail-closed
  `MCP_CURL_DESTINATION_ALLOWLIST`), and `systemctl` (read-only verbs; service
  mutations remain on `change_service_state`). Unsupported invocations are
  rejected before dispatch with typed `PROGRAM_SUBCOMMAND_NOT_PERMITTED` /
  `PROGRAM_ARGUMENT_NOT_PERMITTED` policy codes. The policy applies uniformly
  to `execute_program`, `start_program`, `remote_job_start`, and persisted cron
  arguments.

### Fixed

- `list_docker_containers`/`get_docker_stats` check the Docker CLI exit status
  before parsing: a daemon/permission failure is a typed upstream error with
  bounded sanitized stderr, never a successful empty inventory. Record decoding
  parses JSON first and decodes HTML entities only inside string keys/values,
  with a tested fallback for the historical fully-escaped transport.
- `analyze_disk` captures each phase's producer exit status (df and du
  independently; no reliance on pipeline status) and preserves bounded
  sanitized `du` stderr; failures are typed
  (`REMOTE_COMMAND_FAILED`/`PERMISSION_DENIED`/`TIMEOUT`/`PARSER_FAILED`) and
  partial results name the failed section. Remote tempfiles are cleaned by
  POSIX traps even when the diagnostic is interrupted.
- `list_processes` reports the explicit `ps` producer status (typed failure on
  `ps` error), excludes the wrapper process before applying the 20-record
  budget, and reports `processesTruncated` only when more than 20 usable
  records were observed, with an explicit `observedAt` timestamp.

### Added

- `docs/ci-troubleshooting.md`: recurring hosted-CI and bot-gate friction with
  verified mitigations.
- Acceptance coverage for durable remote jobs (idempotency conflicts, PID-reuse
  protection, output cursor paging, bounded wait, cross-instance recovery,
  retention) and build-provenance distinguishability between source revisions.

 - 2026-09-12

### Added

- Typed SSH program execution with structured `executable`, `argv`, `cwd`, and
  `stdin` inputs; arbitrary shell strings remain unavailable on the public MCP surface.
- Durable SSH remote jobs (`remote_job_start/status/wait/result/output/cancel`)
  with idempotency keys, owner-bound receipts, bounded output cursors,
  disconnect/reconnect reconciliation, cancellation verified against the whole
  process group, and a seven-day retention horizon; activated by
  `MCP_REMOTE_JOB_STORE_FILE`.
- Atomic compare-and-swap file patching through `file_patch_atomic`: a
  caller-supplied content digest is verified against the same opened file
  descriptor before an atomic write, with symlink-rejecting traversal and a
  bounded `CONFLICT` failure that never writes.
- Cron profile management (`cron_list/cron_upsert/cron_remove`) with typed
  schedule fields, marker-anchored idempotent projection into the user
  crontab, concurrent-modification detection, and target-aware removal;
  activated by `MCP_CRON_PROFILE_STORE_FILE`.
- Docker/Compose semantic operations: `docker_runtime_snapshot`, two-step
  `docker_recreate_plan`/`docker_recreate_apply` bound to expiring server-side
  plan receipts with record-derived `PLAN_STALE`/`IMAGE_DRIFT`/`ALREADY_APPLIED`
  and a typed `RECREATE_CONFIG_DRIFT` refusal for unaccepted runtime-only
  drift, plus bounded `service_wait` readiness polling; activated by
  `MCP_DOCKER_PLAN_STORE_FILE`.
- Bounded process-job handles with owner-scoped status, result, cancellation, and
  process-local retention semantics.
- Regression coverage for HTML-escaped mikr.us diagnostics and truthful disk-analysis failures.
- Bounded structured process snapshots with partial-state reporting and secret redaction.
- Immutable build provenance: the exact wheel is stamped at build time with the
  candidate source revision, build ID, policy revision, and package content digest;
  runtime reports `packageIntegrity` (verified/failed/unstamped), a process-local
  `instanceGeneration`, and deployment binding (verified/missing/invalid) validated
  against a deployment receipt. Environment variables can no longer establish
  artifact identity. Wheel builds now run through
  `scripts/build_wheel.py --provenance unstamped|stamped`, which refuses wheels
  rebuilt from sources newer than the stamp.

### Changed

- The typed program execution allowlist is tightened fail-closed: general-purpose
  or mutating executables were removed from `execute_program` and the program
  helpers; service control stays on the dedicated service tools.
- The capability catalog now reports machine-readable inactive reason codes and
  a configuration generation alongside each capability.
- Docker compose recreation requests that outlive the collector work budget can
  no longer succeed silently after the deadline: the helper allowance matches
  the 55-second work budget inside the 65-second execution limit.
- The pinned standards authority migrated to AI Skills `1.4.0`
  (`435061ad67ee36d77e01a993bc4f9e4379a29666`); compliance documentation
  assesses the expanded 27-rule `mcp-server-architect` catalog.

## [2.1.0] - 2026-09-12

### Added

- Typed SSH program execution with structured `executable`, `argv`, `cwd`, and
  `stdin` inputs; arbitrary shell strings remain unavailable on the public MCP surface.
- Durable SSH remote jobs (`remote_job_start/status/wait/result/output/cancel`)
  with idempotency keys, owner-bound receipts, bounded output cursors,
  disconnect/reconnect reconciliation, cancellation verified against the whole
  process group, and a seven-day retention horizon; activated by
  `MCP_REMOTE_JOB_STORE_FILE`.
- Atomic compare-and-swap file patching through `file_patch_atomic`: a
  caller-supplied content digest is verified against the same opened file
  descriptor before an atomic write, with symlink-rejecting traversal and a
  bounded `CONFLICT` failure that never writes.
- Cron profile management (`cron_list/cron_upsert/cron_remove`) with typed
  schedule fields, marker-anchored idempotent projection into the user
  crontab, concurrent-modification detection, and target-aware removal;
  activated by `MCP_CRON_PROFILE_STORE_FILE`.
- Docker/Compose semantic operations: `docker_runtime_snapshot`, two-step
  `docker_recreate_plan`/`docker_recreate_apply` bound to expiring server-side
  plan receipts with record-derived `PLAN_STALE`/`IMAGE_DRIFT`/`ALREADY_APPLIED`
  and a typed `RECREATE_CONFIG_DRIFT` refusal for unaccepted runtime-only
  drift, plus bounded `service_wait` readiness polling; activated by
  `MCP_DOCKER_PLAN_STORE_FILE`.
- Bounded process-job handles with owner-scoped status, result, cancellation, and
  process-local retention semantics.
- Regression coverage for HTML-escaped mikr.us diagnostics and truthful disk-analysis failures.
- Bounded structured process snapshots with partial-state reporting and secret redaction.
- Immutable build provenance: the exact wheel is stamped at build time with the
  candidate source revision, build ID, policy revision, and package content digest;
  runtime reports `packageIntegrity` (verified/failed/unstamped), a process-local
  `instanceGeneration`, and deployment binding (verified/missing/invalid) validated
  against a deployment receipt. Environment variables can no longer establish
  artifact identity. Wheel builds now run through
  `scripts/build_wheel.py --provenance unstamped|stamped`, which refuses wheels
  rebuilt from sources newer than the stamp.

### Changed

- The typed program execution allowlist is tightened fail-closed: general-purpose
  or mutating executables were removed from `execute_program` and the program
  helpers; service control stays on the dedicated service tools.
- The capability catalog now reports machine-readable inactive reason codes and
  a configuration generation alongside each capability.
- Docker compose recreation requests that outlive the collector work budget can
  no longer succeed silently after the deadline: the helper allowance matches
  the 55-second work budget inside the 65-second execution limit.
- The pinned standards authority migrated to AI Skills `1.4.0`
  (`435061ad67ee36d77e01a993bc4f9e4379a29666`); compliance documentation
  assesses the expanded 27-rule `mcp-server-architect` catalog.

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
