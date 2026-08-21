#!/usr/bin/env python3
"""Validate repository workflows against the project's least-privilege profiles."""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
SECRET_REF = re.compile(r"\$\{\{(?:(?!\}\}).)*\bsecrets\b", re.IGNORECASE | re.DOTALL)
EXPRESSION = re.compile(r"\$\{\{")
MUTABLE_RUNNERS = {"ubuntu-latest", "windows-latest", "macos-latest"}


class UniqueLoader(yaml.SafeLoader):
    """YAML loader which rejects duplicate mapping keys."""


def _mapping(loader: UniqueLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"duplicate key {key!r}",
                key_node.start_mark,
            )
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def _events(document: dict[Any, Any]) -> set[str]:
    value = document.get("on", document.get(True))
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return {item for item in value if isinstance(item, str)}
    if isinstance(value, dict):
        return {item for item in value if isinstance(item, str)}
    return set()


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _strings(key)
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _permissions(value: Any, label: str) -> tuple[dict[str, str], list[str]]:
    if not isinstance(value, dict):
        return {}, [f"{label} must declare permissions as a mapping"]
    parsed: dict[str, str] = {}
    findings: list[str] = []
    for key, access in value.items():
        if not isinstance(key, str) or not isinstance(access, str):
            findings.append(f"{label} permission names and values must be strings")
            continue
        normalized = access.casefold()
        if normalized not in {"read", "write", "none"}:
            findings.append(f"{label} has unsupported permission {key}: {access}")
        parsed[key.casefold()] = normalized
    return parsed, findings


def _check_action(path: Path, job_name: str, index: int, step: Any) -> list[str]:
    if not isinstance(step, dict) or "uses" not in step:
        return []
    uses = step["uses"]
    label = f"{path.name}: job {job_name!r} step {index}"
    if not isinstance(uses, str):
        return [f"{label} has non-string uses"]
    findings: list[str] = []
    if not uses.startswith("./"):
        if "@" not in uses:
            findings.append(f"{label} action {uses!r} has no immutable revision")
        else:
            _, revision = uses.rsplit("@", 1)
            if not FULL_SHA.fullmatch(revision):
                findings.append(f"{label} must use a full 40-character SHA")
    action = uses.rsplit("@", 1)[0]
    with_block = step.get("with")
    if action == "actions/checkout":
        if not isinstance(with_block, dict) or with_block.get("persist-credentials") is not False:
            findings.append(f"{label} checkout must set persist-credentials: false")
    if action == "actions/upload-artifact":
        if not isinstance(with_block, dict):
            findings.append(f"{label} upload-artifact requires a with mapping")
        else:
            retention = with_block.get("retention-days")
            if not isinstance(retention, int) or isinstance(retention, bool) or retention <= 0:
                findings.append(f"{label} upload-artifact needs positive retention-days")
            if with_block.get("if-no-files-found") not in {"error", "warn", "ignore"}:
                findings.append(f"{label} upload-artifact needs if-no-files-found")
    return findings


def _allowed_job_permissions(path: Path, job_name: str, events: set[str]) -> dict[str, set[str]]:
    if "pull_request" in events:
        if path.name == "semgrep.yml" and job_name == "semgrep":
            return {"contents": {"read", "none"}, "security-events": {"write", "none"}}
        return {"contents": {"read", "none"}}
    if path.name == "publish.yml" and job_name == "validate-release":
        return {"contents": {"read", "none"}, "actions": {"read", "none"}}
    if path.name == "publish.yml" and job_name == "publish":
        return {
            "contents": {"read", "none"},
            "actions": {"read", "none"},
            "packages": {"write", "none"},
            "id-token": {"write", "none"},
            "attestations": {"write", "none"},
        }
    if path.name == "semgrep-scheduled.yml" and job_name == "semgrep":
        return {"contents": {"read", "none"}, "security-events": {"write", "none"}}
    return {"contents": {"read", "none"}}


def audit(path: Path) -> list[str]:
    try:
        document = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueLoader)
    except (OSError, yaml.YAMLError) as exc:
        return [f"{path.name}: cannot parse workflow: {exc}"]
    if not isinstance(document, dict):
        return [f"{path.name}: workflow root must be a mapping"]

    findings: list[str] = []
    events = _events(document)
    if not events:
        findings.append(f"{path.name}: workflow must declare events")
    if "pull_request_target" in events:
        findings.append(f"{path.name}: pull_request_target is forbidden")

    top_permissions, permission_findings = _permissions(
        document.get("permissions"), f"{path.name}: workflow"
    )
    findings.extend(permission_findings)
    if "pull_request" in events:
        for scope, access in top_permissions.items():
            if scope != "contents" or access not in {"read", "none"}:
                findings.append(
                    f"{path.name}: pull-request workflow grants forbidden {scope}: {access}"
                )
        if any(SECRET_REF.search(item) for item in _strings(document)):
            findings.append(f"{path.name}: pull-request workflow references secrets")

    concurrency = document.get("concurrency")
    if not isinstance(concurrency, dict):
        findings.append(f"{path.name}: concurrency must be a mapping")
    else:
        if not isinstance(concurrency.get("group"), str) or not concurrency["group"].strip():
            findings.append(f"{path.name}: concurrency group must be non-empty")
        if not isinstance(concurrency.get("cancel-in-progress"), bool):
            findings.append(f"{path.name}: cancel-in-progress must be boolean")

    jobs = document.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        return [*findings, f"{path.name}: workflow must contain jobs"]
    for raw_name, raw_job in jobs.items():
        job_name = str(raw_name)
        if not isinstance(raw_job, dict):
            findings.append(f"{path.name}: job {job_name!r} must be a mapping")
            continue
        runner = raw_job.get("runs-on")
        if not isinstance(runner, str) or not runner.strip():
            findings.append(f"{path.name}: job {job_name!r} needs a literal runner")
        elif runner.casefold() in MUTABLE_RUNNERS or EXPRESSION.search(runner):
            findings.append(f"{path.name}: job {job_name!r} uses mutable runner {runner!r}")
        timeout = raw_job.get("timeout-minutes")
        if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
            findings.append(f"{path.name}: job {job_name!r} needs positive timeout-minutes")

        permissions, job_permission_findings = _permissions(
            raw_job.get("permissions", document.get("permissions")),
            f"{path.name}: job {job_name!r}",
        )
        findings.extend(job_permission_findings)
        allowed = _allowed_job_permissions(path, job_name, events)
        for scope, access in permissions.items():
            if scope not in allowed or access not in allowed[scope]:
                findings.append(
                    f"{path.name}: job {job_name!r} grants unexpected {scope}: {access}"
                )
        if path.name == "publish.yml" and job_name == "publish":
            if raw_job.get("environment") != "release":
                findings.append(
                    f"{path.name}: publish job must use the protected release environment"
                )
            steps = raw_job.get("steps")
            if isinstance(steps, list):
                for index, step in enumerate(steps, start=1):
                    if isinstance(step, dict) and str(step.get("uses", "")).startswith(
                        "actions/checkout@"
                    ):
                        findings.append(
                            f"{path.name}: publish step {index} must not checkout candidate source"
                        )

        steps = raw_job.get("steps")
        if not isinstance(steps, list):
            findings.append(f"{path.name}: job {job_name!r} steps must be a list")
            continue
        for index, step in enumerate(steps, start=1):
            findings.extend(_check_action(path, job_name, index, step))
    return findings


def main() -> int:
    paths = sorted([*WORKFLOW_DIR.glob("*.yml"), *WORKFLOW_DIR.glob("*.yaml")])
    findings = [finding for path in paths for finding in audit(path)]
    if findings:
        for finding in findings:
            print(f"ERROR: {finding}", file=sys.stderr)
        return 1
    print(f"workflow policy: PASS ({len(paths)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
