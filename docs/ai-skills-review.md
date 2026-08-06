---
description: Review findings and proposed amendments for the ai-skills 1.2.0 standards and templates
doc_id: reference.ai-skills-upstream-review
type: reference
status: evolving
rigor: informative
owners: [repository-maintainers]
verification: Compare each finding with the immutable ai-skills 1.2.0 standard, generator, template, contract, and current MCP protocol/SDK release before upstreaming.
---
# AI Skills upstream review

## Findings

### Exact Python artifact guidance conflicts with generated container paths

The MCP standard requires building one wheel, testing that exact wheel, copying the same wheel into the image, verifying its digest, and never rebuilding the package from source inside the image. The Python generator and CI templates should be checked mechanically to ensure every generated Dockerfile and hosted workflow follows that rule. A generator regression should fail whenever `pip install .`, editable installation, or source rebuild appears in an artifact acceptance path.

### Generated acceptance should distinguish source tests from installed-wheel tests

Editable or source-tree test execution is useful during development but cannot establish `mcp.artifact.exact`. The standard would be clearer if the generated baseline required separate named jobs for source quality, exact wheel installation, official-client wheel smoke, image-from-wheel, and pushed-digest smoke. Each evidence claim should identify which artifact it proves.

### Adoption controls are too coarse for independent failures

The current MCP catalog maps large normative sections to single rule IDs. One `mcp.response.structured` result can hide independent failures in protocol-native errors, output bounds, provenance, confidentiality minimization, partial state, or schemas. Preserve stable parent rules but add atomic child controls and require evidence for each applicable child.

### Consumer repositories need a canonical skill lock

README guidance says consumers should pin both repository revision and skill version, but there is no small mandatory consumer-side lock contract. Add an `ai-skills.lock.yaml` schema containing repository identity, full commit SHA, selected skill versions, protocol revisions, and verifier identity. Validators should reject mutable branch URLs, stale vendored validators, and version drift.

### AFDS needs an explicit legacy-schema migration path

Older adopters can contain `type: ref`, `rigor_tier`, `ttl_days`, `last_verified`, broad exemptions, and a historical validator while appearing AFDS-enabled. Add a configuration schema version, a migration diagnostic for legacy fields, and an adoption test proving that the canonical validator—not a stale local copy—owns approval. Clarify which root files may be exempt from structure and which metadata rules still apply.

### Protocol revision is a missing compatibility axis

SDK package version and MCP protocol revision are related but independent. The 2026-07-28 protocol revision introduces materially different negotiation and request metadata. Add declared `protocol_revisions` to manifests, compatibility matrices, generator tests, and adoption evidence. Require explicit results for the current production revision and each supported compatibility revision.

### Provider-backed evidence should expose an adapter contract

The current acceptance implementation is intentionally specific to public GitHub.com and GitHub Actions. Publish a provider adapter interface that defines trusted API origins, run/job/artifact identity, immutable source binding, result digests, review identity, and retention. Other providers can then remain unsupported without making the domain model appear GitHub-specific.

### Multi-architecture promotion is underspecified

“Build once and promote the same image” needs a precise OCI playbook for multiple platforms. Define per-platform OCI layout/digest production, native or emulated smoke requirements, manifest-list assembly without rebuild, final index digest attestation, and verification that every platform digest in the index was tested.

### Stable skill maturity and adopter approval need clearer wording

A stable skill means the standard and its own compatibility evidence are stable; it does not mean an adopting repository is compliant. Templates, README text, and adoption reports should use distinct terms for skill maturity, structural conformance, diagnostic local evidence, provider-backed acceptance, and independent production approval.

## Proposed upstream changes

1. Add atomic child controls under each broad adoption rule.
2. Add `ai-skills.lock.yaml` and its validator.
3. Add protocol revision to every MCP compatibility declaration.
4. Add generator tests that reject source rebuilds in exact-artifact lanes.
5. Add an AFDS legacy migration command and schema-versioned configuration.
6. Publish a provider adapter interface and a multi-architecture OCI promotion reference workflow.
7. Tighten terminology so local green tests cannot be reported as independent approval.
