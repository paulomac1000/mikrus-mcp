#!/usr/bin/env python3
"""Run repository-local documentation and stale-contract checks without network access."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
GOVERNED = [
    ROOT / "AGENTS.md",
    ROOT / "SECURITY.md",
    ROOT / "MIGRATION.md",
    ROOT / "docs/architecture.md",
    ROOT / "docs/compliance-status.md",
    ROOT / "docs/ai-skills-review.md",
]
REQUIRED = {"description", "doc_id", "type", "status", "rigor", "owners", "verification"}
STALE = (
    "run_sse_async",
    "MCP_UNSAFE_PUBLIC_ACCESS_CONFIRMED",
    "FastMCP(",
    "_lifespan_data",
    "mcp.get_context()",
    "/var/apps/",
)


def metadata(path: Path) -> tuple[dict[str, object], str]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    if match is None:
        raise ValueError(f"{path.relative_to(ROOT)}: missing YAML frontmatter")
    parsed = yaml.safe_load(match.group(1))
    if not isinstance(parsed, dict):
        raise ValueError(f"{path.relative_to(ROOT)}: frontmatter must be a mapping")
    return parsed, text[match.end() :]


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument(
        "--print-governed",
        action="store_true",
        help="print governed document paths for the pinned upstream validator",
    )
    return value


def main() -> int:
    args = parser().parse_args()
    if args.print_governed:
        print("\n".join(str(path.relative_to(ROOT)) for path in GOVERNED))
        return 0
    findings: list[str] = []
    identifiers: set[str] = set()
    for path in GOVERNED:
        if not path.is_file():
            findings.append(f"missing governed document: {path.relative_to(ROOT)}")
            continue
        try:
            values, body = metadata(path)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            findings.append(str(exc))
            continue
        missing = sorted(REQUIRED - set(values))
        if missing:
            findings.append(f"{path.relative_to(ROOT)}: missing {', '.join(missing)}")
        doc_id = values.get("doc_id")
        if not isinstance(doc_id, str) or doc_id in identifiers:
            findings.append(f"{path.relative_to(ROOT)}: invalid or duplicate doc_id")
        else:
            identifiers.add(doc_id)
        headings = re.findall(r"^#\s+.+$", body, re.M)
        if len(headings) != 1:
            findings.append(f"{path.relative_to(ROOT)}: expected exactly one H1")

    production = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "src/mikrus_mcp").rglob("*.py")
    )
    for marker in STALE:
        if marker in production:
            findings.append(f"stale production contract remains: {marker}")

    lock = yaml.safe_load((ROOT / "ai-skills.lock.yaml").read_text(encoding="utf-8"))
    revision = lock.get("revision") if isinstance(lock, dict) else None
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        findings.append("ai-skills.lock.yaml must pin a full commit SHA")

    if findings:
        print("\n".join(findings), file=sys.stderr)
        return 1
    print(f"Validated {len(GOVERNED)} governed documents and repository contracts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
