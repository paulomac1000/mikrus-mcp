---
afds_schema_version: 2
description: Repository-wide operating contract for agents changing the hardened mikrus-mcp server
doc_id: guide.agent-contribution
type: guide
status: active
rigor: operational
owners: [repository-maintainers]
verification:
  kind: command
  value: Run `.venv/bin/python scripts/core_gate.py`, then `.venv/bin/python scripts/ci.py` in the locked development environment and verify provider CI on the exact final revision.
---
# Repository instructions for agents

## Scope and precedence

This file applies to the complete repository. Direct user instructions and platform
safety requirements have higher authority. Normative architecture and security rules
live in [Architecture](docs/architecture.md) and [Security model](SECURITY.md).
Conflicts fail closed; identify the competing sources instead of choosing the easier
rule.

The pinned standards revision is recorded in [`ai-skills.lock.yaml`](ai-skills.lock.yaml).
Read the applicable `STANDARD.md` from that revision before changing MCP, AFDS,
AGENTS.md, or CI/CD contracts.

## Operating modes

- **Read-only audit:** inspect code, tests, documentation, configuration, and provider
  evidence without modifying the repository or external systems.
- **Implementation:** modify the work branch only; do not publish, tag, deploy, send
  data, or access a real backend without explicit authorization.
- **Migration:** update canonical rules, implementation, tests, documentation, and
  compatibility notes together.
- **Release:** requires exact-revision CI, exact-artifact smoke, protected environment,
  immutable digest, and provider-backed review.
- **Real-system validation:** use dedicated test targets and the TODO tests under
  `tests/real_system/`; never repurpose production infrastructure.

## Architecture boundaries

- `config.py` owns the immutable process settings snapshot.
- `manifests.py` owns capability policy metadata. Missing metadata is a startup error.
- `kernel.py` is the only public operation path. Transports and tests do not call
  backend methods around it.
- `client.py` contains MCP-independent mikr.us and SSH adapters.
- `server.py` owns official SDK registration and transport composition.
- `http.py` owns loopback Host, Origin, and request-body controls.
- `validators.py` performs local validation before protected I/O.
- `sanitizer.py` performs field-aware model-visible minimization.
- No unavailable or failed target may be replaced with another target.
- No model argument, boolean, description prefix, or natural-language confirmation is
  authorization or approval.

Do not reintroduce SDK v1 private attributes, legacy HTTP+SSE, production test mocks,
import-time client creation, mutable global request context, broad shell execution, or
lexical path-prefix containment.

## Commands

Create an isolated environment:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install "pip==26.1.2"
.venv/bin/python -m pip install --require-hashes -r requirements-dev-linux-x64-py312.lock
.venv/bin/python -m pip install --no-deps .
```

Focused test:

```bash
.venv/bin/python -m pytest tests/unit/test_kernel.py -q
```

Credential-free core gate:

```bash
.venv/bin/python scripts/core_gate.py
```

Complete local gate:

```bash
.venv/bin/python scripts/ci.py
```

Build and inspect the exact wheel:

```bash
.venv/bin/python -m build --wheel
.venv/bin/python scripts/artifact_smoke.py \
  --wheel dist/mikrus_mcp-2.1.0-py3-none-any.whl \
  --wheelhouse wheelhouse
```

Real-backend tests are skipped by default. Run them only with dedicated credentials,
explicit target selection, write policy, and approval records.

## Safety and data boundaries

Secrets, approval files, private keys, known-host databases, real logs, database
credentials, production exports, and test output containing protected data stay
outside tracked files. Never print them to stdout, logs, failure messages, artifacts,
or PR comments.

Stdio reserves stdout for MCP protocol traffic. Diagnostics go to stderr. Streamable
HTTP remains loopback-only until a separately reviewed remote-auth profile exists.
Writes are disabled by default and require a one-time server-side approval bound to
the principal, capability, target, and resource. For SSH mutations, the trusted
approval workflow first connects using host-key verification and binds the approval to
the verified peer fingerprint. Approval identifiers remain outside MCP schemas; issue
records only through the trusted local operator workflow.

Do not weaken, delete, skip, or rewrite assertions solely to obtain a green result.
When a check needs infrastructure unavailable to the current agent, add a narrowly
scoped skipped test with a concrete `TODO(real-system)` or `TODO(provider)` reason and
record the missing evidence in [Compliance status](docs/compliance-status.md).

## Documentation routes

- Architecture, boundaries, lifecycle, failures: `docs/architecture.md`
- Threat model and operator controls: `SECURITY.md`
- Standards rule evidence and residual gaps: `docs/compliance-status.md`
- Breaking upgrade workflow: `MIGRATION.md`
- Upstream standards defects and proposals: `docs/ai-skills-review.md`
- User setup and supported workflows: `README.md`

## Definition of done

A change is complete only when code, manifests, schemas, documentation, and tests
agree; local and hosted commands are distinct; target and approval bindings remain
fail-closed; exact built artifacts are tested; new residual risk is recorded; and
provider checks and review refer to the exact final commit. Local self-review is not
independent production approval.
