---
afds_schema_version: 2
description: Recurring hosted-CI and bot-gate friction on this repository with verified working mitigations
doc_id: guide.ci-troubleshooting
type: guide
status: active
rigor: operational
owners: [repository-maintainers]
verification:
  kind: command
  value: Re-apply the documented mitigation for the affected gate and confirm the gate passes on the exact final revision (provider CI or `scripts/ci.py` locally).
---
# CI and bot-gate friction runbook

Four operational problems recurred during the 2.1.0 delivery (PR #25) and are
expected to recur on future pushes. Each section states the symptom, the root
cause, and the mitigation verified working during that delivery. Steward issue
`MIKRUS-2D96A6-3` tracks this runbook.

## 1. Platform-lock regeneration drift

**Symptom.** The hosted CI "Platform locks" job fails, or a locally regenerated
lock differs from what the CI runner resolves, even though
`requirements-*.in` inputs did not change.

**Root cause.** Two independent drift sources:

- upstream PyPI state moves between the time locks were generated and the time
  the runner re-resolves them;
- a stale local pip HTTP cache can serve outdated artifacts. During PR #25 a
  local cache served `pyjwt 2.13.0` while the runners resolved `pyjwt 2.14.0`,
  producing locks that CI could not reproduce.

**Verified mitigation.** Regenerate locks inside the same images the CI matrix
uses — `python:3.12-slim`, `python:3.13-slim`, and `python:3.14-slim` — with
pinned resolution tooling (`pip==26.2.1`, `pip-tools==7.6.1`) and a **fresh**
`PIP_CACHE_DIR`; copy the rendered locks into the repository. The CI lane itself
pins `pip==$PIP_VERSION pip-tools==7.6.1` (`.github/workflows/ci.yml`).

**Durable options.** Pin resolution-time tooling in-repo, or vendor a
lock-refresh CI lane so local regeneration is never needed.

## 2. Evidence-freshness binding invalidated by every commit

**Symptom.** `scripts/check_evidence_freshness.py` fails after an ordinary
implementation commit with a message about the assessed revision no longer
being an ancestor of `HEAD`.

**Root cause.** `docs/compliance-status.md` frontmatter binds
`assessed_revision` (a full 40-character SHA) that must be an ancestor of
`HEAD` with only evidence-path drift after it. Any implementation commit after
the last evidence binding invalidates the gate until evidence is rebound.

**Verified mitigation.** Follow each implementation commit with an
evidence-only rebind commit (see the two `docs: rebind ...` commits in the
2.1.0 history) after re-running the provider evidence for the new revision.
Squash merges require fresh provider evidence for the squash commit before
freshness can be claimed.

**Durable options.** Automate the assessed-revision binding into release
tooling, or relax the gate to accept implementation commits between bindings
within one PR. Neither is implemented; the manual rebind is currently the
supported workflow.

## 3. CodeRabbit free-tier review quota

**Symptom.** CodeRabbit reviews are delayed or skipped after consecutive
pushes; a review cycle can take 30–60 minutes.

**Root cause.** The free tier burns quota per push with a roughly 30–60 minute
rolling reset, which blocks timely bot-review cycles on active branches.

**Verified mitigation.** Pace pushes so each review cycle completes before the
next push, and batch unrelated review-triggering commits.

**Durable options.** Paid CodeRabbit tier or a self-hosted review bot removes
the quota constraint; neither is configured for this repository.

## 4. No external TCP/22 forward to the mikr.us VPS

**Symptom.** Standard SSH (TCP/22) cannot reach the production mikr.us VPS
from outside the platform, so the production host is not reachable as a
real-system test target over the conventional port.

**Root cause.** The mikr.us platform port-forward set for this VPS does not
expose TCP/22 (verified refused from two independent networks during PR #25).
The SSH daemon runs internally on TCP/22 only. Any external SSH access exists
solely through operator-assigned platform forwards (for example a non-standard
port), and is available only as actually configured for the specific server.

**Verified mitigation.** Collect real-system evidence on a dedicated
operator-directed target, reached through whatever operator-assigned endpoint
that target provides. `tests/real_system/` carries the deferred tests with
concrete `TODO(real-system)` reasons; they stay skipped without dedicated
credentials, explicit target selection, write policy, and approval records.
Never repurpose production infrastructure as a test target. Every real-system
evidence record states which target it was collected against
(see `docs/compliance-status.md`, "real-system evidence").

**Durable options.** A working TCP/22 forward from the platform, or a
permanently provisioned dedicated test host.
