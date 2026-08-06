---
description: Rule-by-rule adoption status and remaining evidence for ai-skills 1.2.0 compliance
doc_id: reference.ai-skills-compliance-status
type: reference
status: evolving
rigor: operational
owners: [repository-maintainers]
verification: Run python scripts/ci.py, inspect provider-backed jobs on the exact commit, and complete every deferred test in tests/real_system before an approval claim.
---
# AI Skills compliance status

## Scope

This assessment applies the `mcp-server-architect`, `agents-md-architect`, `afds-doc-writer`, and `ci-cd-architect` standards from `paulomac1000/ai-skills` release 1.2.0 to this repository. Local results are diagnostic. This document does not claim independent provider-backed production approval.

## MCP server rules

| Rule | Status | Evidence or remaining work |
| --- | --- | --- |
| `mcp.architecture.boundaries` | implemented locally | Typed settings, application manifests, target registry, one invocation kernel, thin MCP registration, and transport composition are separated. |
| `mcp.identity.target-binding` | implemented locally; real SSH evidence deferred | Unknown/unavailable targets fail without fallback; stable identity is checked after client creation. Complete real fingerprint enrollment/revalidation. |
| `mcp.manifest.complete` | implemented locally | Startup validates exact active registration and manifest consistency. Command execution is a separate inactive profile. |
| `mcp.retry.fail-closed` | implemented locally; real mutation reconciliation deferred | Mutations are non-idempotent and non-retryable; reads honor bounded rate-limit policy. Complete real ambiguous-outcome tests. |
| `mcp.transport.supported` | implemented locally | stdio and stateless Streamable HTTP only; legacy HTTP+SSE and REST bridge removed. |
| `mcp.deadline.concurrency` | implemented locally | Per-manifest deadlines, bounded bodies/results/output, serialized rate reservations, and keyed locks for unsafe operations. |
| `mcp.response.structured` | implemented locally | Typed MCP callables return structured content and raise protocol-native `ToolError`; field-aware redaction is tested. |
| `mcp.authorization.server-side` | implemented locally | Process principal/scopes, exact target authorization, operator gates, and persistent one-time approval consumption are enforced server-side. |
| `mcp.operations.observable` | partial | Request IDs, durations, readiness, target status, and stderr logging exist. Production SLOs, metrics, traces, and recovery drills remain deployment work. |
| `mcp.artifact.exact` | implemented on local Linux; provider matrix deferred | CI builds a wheel, installs that exact wheel without dependency resolution, smokes it through the official client, and builds the image from that wheel. macOS/Windows and pushed OCI digest evidence remain deferred. |
| `mcp.migration.accounted` | implemented as repository documentation | `MIGRATION.md`, changelog, rollback notes, breaking behavior, and residual risks are explicit. A formal provider-backed adoption assessment is still required for approval. |
| `mcp.verification.layered` | local layers implemented; external lanes deferred | Unit, mocked application, official-client, registration, HTTP boundary, wheel, and container workflows exist. Real-system and provider-backed layers remain marked TODO. |

## AGENTS.md rules

The root instruction file declares read-only audit and implementation modes, repository boundaries, exact local/hosted commands, canonical owners, safety rules, residual evidence, and definition of done. It avoids host-specific absolute references, volatile tool counts, embedded workflow duplication, and obsolete SSE/REST instructions. Static and platform-specific loading validation should be supplied by a pinned external `agents-md-architect` verifier in provider CI.

## AFDS rules

Governed Markdown documents use the current metadata model (`reference`, `system`, `guide`, `contract`; `rigor`; non-empty owners and verification). `docs/documents.yaml` declares the governed set, and `scripts/check_docs.py` enforces metadata, stable IDs, uniqueness, and forbidden automation-owned fields. The final adoption gate should also run the canonical AFDS validator from a pinned immutable `ai-skills` revision.

## CI/CD rules

Workflows use least-privilege permissions, full action SHAs, disabled checkout credentials, timeouts, concurrency, Python compatibility lanes, local parity scripts, security checks, documentation validation, exact wheel smoke, and a no-rebuild container path. Publication remains protected and must promote the already tested artifact. Provider-backed status, retained evidence, review identity, and multi-architecture digest smoke are not available from the local environment.

## Deferred acceptance evidence

The following skipped tests are intentional placeholders for an agent with real systems and provider access:

- stable SSH host fingerprint enrollment and revalidation;
- real mikr.us mutation reconciliation after ambiguous outcomes;
- remote symlink-swap and filesystem TOCTOU resistance;
- exact-wheel compatibility on macOS arm64 and Windows x64;
- smoke of the pushed multi-architecture OCI digest on amd64 and arm64.

Until those checks and the hosted security/tooling gates pass on the exact final commit, the project should be described as locally refactored toward L2/L3 requirements, not independently approved as production compliant.
