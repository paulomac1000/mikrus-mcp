#!/usr/bin/env python3
"""
AFDS Documentation Validator

Validates documentation files against the AI-First Documentation Standard.

Usage:
  python skills/afds-doc-writer/docs_validate.py docs/
  python skills/afds-doc-writer/docs_validate.py --config skills/afds-doc-writer/afds_config.yaml docs/
  python skills/afds-doc-writer/docs_validate.py --pre-commit file.md
  python skills/afds-doc-writer/docs_validate.py --report

Exit Codes:
  0 - All checks passed
  1 - Blocking errors found
"""

import argparse
import json
import os
import re
import sys
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, date
from pathlib import Path
from typing import Callable, Optional

import yaml


# ---------------------------------------------------------------------------
# Default configuration — embedded fallback when no config file is provided
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "types": {
        "workflow": {
            "id_prefix": "workflow",
            "default_ttl": 90,
            "sections": [
                "PURPOSE", "SCOPE", "TRIGGER", "STEPS", "VALIDATION",
                "PITFALLS", "ROLLBACK",
            ],
        },
        "ref": {
            "id_prefix": "ref",
            "default_ttl": 180,
            "sections": [
                "PURPOSE", "SCOPE", "DEFINITIONS", "RULES", "INTERFACES",
                "STATE", "EDGE_CASES", "EXAMPLES", "NON_GOALS",
            ],
        },
        "system": {
            "id_prefix": "sys",
            "default_ttl": 90,
            "sections": [
                "PURPOSE", "SCOPE", "ARCHITECTURE", "ENTITY_REFERENCE",
                "INTERFACES", "STATE", "EDGE_CASES", "FAILURE_MODES",
                "TESTING", "TROUBLESHOOTING",
            ],
        },
        "guide": {
            "id_prefix": "guide",
            "default_ttl": 180,
            "sections": [
                "PURPOSE", "AUDIENCE", "CONTEXT", "WALKTHROUGH",
                "PITFALLS", "RELATED_DOCS",
            ],
        },
        "decision": {
            "id_prefix": "decision",
            "default_ttl": 0,
            "sections": [
                "CONTEXT", "DECISION", "ALTERNATIVES_CONSIDERED",
                "CONSEQUENCES", "STATUS", "CHANGELOG",
            ],
        },
        "contract": {
            "id_prefix": "contract",
            "default_ttl": 0,
            "sections": [
                "PURPOSE", "SPECIFICATION", "VERSIONING", "CHANGELOG",
            ],
        },
    },
    "statuses": ["active", "draft", "deprecated", "evolving", "archived"],
    "decision_statuses": ["proposed", "accepted", "rejected", "deprecated", "superseded"],
    "ai_scope_values": ["editable", "review_only", "restricted"],
    "stability_values": ["experimental", "stable", "frozen"],
    "rigor_tier_values": ["L0", "L1", "L2", "L3"],
    "allowed_fields": [
        "description", "doc_id", "type", "status", "rigor_tier",
        "ttl_days", "ttl_policy", "stability", "ai_scope",
        "upstream", "last_verified",
        "trigger", "timeout", "scope", "supersedes", "superseded_by",
        "source_of_truth", "domain", "tags", "owners",
        "verification_status", "evidence", "verified_against",
        "generated_by", "doc_kind", "derived_from", "glossary_terms",
        "access_tier", "allowed_roles", "audit_log",
        "language", "canonical", "version",
    ],
    "forbidden_fields": [
        "downstream",
        "verified_by",
        "fitness_score",
        "semantic_hash",
    ],
    "project_banned_words": [],
    "root_files": {},
    "default_paths": ["docs/"],
    "excluded_dirs": ["archived", "archive"],
    "exempt_files": [],
    "normative_sections": [
        "RULES", "INTERFACES", "VALIDATION", "SPECIFICATION",
        "FAILURE_MODES",
    ],
    "non_normative_sections": [
        "EXAMPLES", "NON_GOALS", "PURPOSE", "CONTEXT", "RATIONALE",
        "TRADEOFFS", "WALKTHROUGH", "AUDIENCE", "PITFALLS",
    ],
    "baseline_path": ".afds-baseline.json",
}

# Universal banned words (ambiguity killers, enforced at all tiers)
UNIVERSAL_BANNED_WORDS = [
    r"\bmight\b", r"\bmaybe\b", r"\bpossibly\b", r"\bprobably\b",
    r"\boften\b", r"\bsometimes\b", r"\busually\b", r"\bgenerally\b",
    r"\btypically\b", r"\betc\b", r"\bsimply\b", r"\bjust\b",
]

# Inline metadata patterns to detect
INLINE_METADATA_PATTERNS = [
    r"^\*\*Version:\*\*", r"^\*\*Last Updated:\*\*", r"^\*\*Date:\*\*",
    r"^Version: ", r"^Date: ", r"document_metadata:",
    r"^\| Version \|", r"^\| Last Updated \|",
]

# Global registry for duplicate doc_id detection
_doc_id_registry: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    file_path: str
    passed: bool = True
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    fitness_score: float = 0.0
    suppressed_errors: int = 0
    suppressed_warnings: int = 0


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def deep_merge(base: dict, overlay: dict) -> dict:
    """Deep merge overlay into base. Lists are replaced, dicts are merged."""
    result = deepcopy(base)
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def load_config(config_path: Optional[Path]) -> dict:
    """Load configuration, merging with defaults."""
    if config_path and config_path.exists():
        try:
            user_config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            return deep_merge(DEFAULT_CONFIG, user_config)
        except yaml.YAMLError as e:
            print(f"Warning: invalid config YAML ({e}), using defaults", file=sys.stderr)
    return deepcopy(DEFAULT_CONFIG)


# ---------------------------------------------------------------------------
# File loading
# ---------------------------------------------------------------------------

def load_markdown_file(file_path: Path) -> tuple[Optional[dict], str]:
    """Load a markdown file and extract frontmatter."""
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as e:
        return None, f"Could not read file: {e}"

    if not content.startswith("---"):
        return {}, content

    try:
        end_match = re.search(r"\n---\n", content[3:])
        if not end_match:
            return None, "Invalid frontmatter: missing closing ---"

        frontmatter_str = content[3:end_match.start() + 3]
        body = content[3 + end_match.end():]

        try:
            frontmatter = yaml.safe_load(frontmatter_str)
        except yaml.YAMLError as e:
            return None, f"Invalid YAML frontmatter: {e}"

        return frontmatter, body
    except Exception as e:
        return None, f"Error parsing frontmatter: {e}"


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _blank_code_blocks(text: str) -> str:
    """Replace fenced code block bodies with blank lines to preserve offsets."""
    def replacer(match: re.Match) -> str:
        inner = match.group(2)
        return match.group(1) + "\n" * inner.count("\n") + match.group(3)
    return re.sub(r"(```[^\n]*\n)([\s\S]*?)(```)", replacer, text)


def _extract_all_section_names(body: str) -> list[str]:
    """Extract all ## section names from body, preserving order."""
    body_cleaned = _blank_code_blocks(body)
    pattern = re.compile(r"^## (.+)$", re.MULTILINE)
    return [
        m.group(1).strip().upper().replace(" ", "_")
        for m in pattern.finditer(body_cleaned)
    ]


def _clean_prose(text: str) -> str:
    """Remove code blocks, tables, definitions, and inline code from prose."""
    prose = re.sub(r"```[\s\S]*?```", "", text)
    prose = re.sub(r"\|[^|\n]+\|[^|\n]+\|", "", prose)
    prose = re.sub(r"^- `?\w+`?:", "", prose, flags=re.MULTILINE)
    prose = re.sub(r"`[^`]+`", "", prose)
    prose = re.sub(r"\b(SHOULD|MUST|MAY|ALWAYS|NEVER)\b", "", prose, flags=re.IGNORECASE)
    return prose


def _extract_section_text(body: str, section_name: str) -> str:
    """Extract text belonging to a specific ## section heading."""
    pattern = rf"^## {re.escape(section_name)}\s*\n([\s\S]*?)(?=\n## |\Z)"
    match = re.search(pattern, body, re.MULTILINE)
    return match.group(1) if match else ""


def is_exempt_file(file_path: Path, config: dict) -> bool:
    """Check if a file is exempt from body schema validation."""
    exempt = config.get("exempt_files", [])
    path_str = str(file_path)
    for pattern in exempt:
        if pattern in path_str:
            return True
    return False


# ---------------------------------------------------------------------------
# Validation checks
# ---------------------------------------------------------------------------

def check_frontmatter_present(
    result: ValidationResult, frontmatter: Optional[dict], body: str, file_path: Path, config: dict
) -> None:
    if frontmatter is None:
        result.errors.append("Missing or invalid YAML frontmatter")
        result.passed = False


def check_description_exists(
    result: ValidationResult, frontmatter: Optional[dict], body: str, file_path: Path, config: dict
) -> None:
    if not frontmatter:
        return
    if "description" not in frontmatter:
        result.errors.append("Missing required field: description")
        result.passed = False
    elif not isinstance(frontmatter.get("description"), str):
        result.errors.append("Field 'description' must be a string")
        result.passed = False
    elif str(frontmatter.get("description", "")).rstrip().endswith("."):
        result.errors.append("Field 'description' must not end with a period")
        result.passed = False


def check_doc_id_format(
    result: ValidationResult, frontmatter: Optional[dict], body: str, file_path: Path, config: dict
) -> None:
    if not frontmatter or "doc_id" not in frontmatter:
        return

    doc_id = frontmatter["doc_id"]
    pattern = r"^[a-z][a-z0-9]*(\.[a-z0-9][a-z0-9\-]*)+$"
    if not re.match(pattern, doc_id):
        result.errors.append(
            f"Invalid doc_id format: '{doc_id}' (expected: <type>.<name>)"
        )
        result.passed = False
        return

    # Validate that the prefix matches a known type id_prefix
    prefix = doc_id.split(".")[0]
    known_prefixes = [t["id_prefix"] for t in config["types"].values()]
    if prefix not in known_prefixes:
        result.warnings.append(
            f"doc_id prefix '{prefix}' does not match any configured type id_prefix"
        )


def check_type_valid(
    result: ValidationResult, frontmatter: Optional[dict], body: str, file_path: Path, config: dict
) -> None:
    if not frontmatter or "type" not in frontmatter:
        return
    doc_type = frontmatter["type"]
    valid_types = list(config["types"].keys())
    if doc_type not in valid_types:
        result.errors.append(
            f"Invalid type: '{doc_type}' (valid: {', '.join(valid_types)})"
        )
        result.passed = False


def check_status_valid(
    result: ValidationResult, frontmatter: Optional[dict], body: str, file_path: Path, config: dict
) -> None:
    if not frontmatter or "status" not in frontmatter:
        return
    status = frontmatter["status"]
    doc_type = frontmatter.get("type")
    # Decision documents use their own lifecycle statuses
    if doc_type == "decision":
        valid_statuses = config.get("decision_statuses", [
            "proposed", "accepted", "rejected", "deprecated", "superseded",
        ])
    else:
        valid_statuses = config["statuses"]
    if status not in valid_statuses:
        result.errors.append(
            f"Invalid status: '{status}' (valid: {', '.join(valid_statuses)})"
        )
        result.passed = False


def check_ttl_days_integer(
    result: ValidationResult, frontmatter: Optional[dict], body: str, file_path: Path, config: dict
) -> None:
    if not frontmatter or "ttl_days" not in frontmatter:
        return
    ttl = frontmatter["ttl_days"]
    if ttl == "∞":
        return
    if not isinstance(ttl, (int, float)) or ttl < 0:
        result.errors.append(f"ttl_days must be a non-negative integer, got: {ttl!r}")
        result.passed = False


def check_ai_scope_valid(
    result: ValidationResult, frontmatter: Optional[dict], body: str, file_path: Path, config: dict
) -> None:
    if not frontmatter or "ai_scope" not in frontmatter:
        return
    ai_scope = frontmatter["ai_scope"]
    if ai_scope not in config["ai_scope_values"]:
        result.errors.append(
            f"Invalid ai_scope: '{ai_scope}' (valid: {', '.join(config['ai_scope_values'])})"
        )
        result.passed = False


def check_stability_valid(
    result: ValidationResult, frontmatter: Optional[dict], body: str, file_path: Path, config: dict
) -> None:
    if not frontmatter or "stability" not in frontmatter:
        return
    stability = frontmatter["stability"]
    if stability not in config["stability_values"]:
        result.errors.append(
            f"Invalid stability: '{stability}' (valid: {', '.join(config['stability_values'])})"
        )
        result.passed = False


def check_strict_frontmatter(
    result: ValidationResult, frontmatter: Optional[dict], body: str, file_path: Path, config: dict
) -> None:
    if not frontmatter:
        return
    allowed = set(config["allowed_fields"])
    forbidden = set(config["forbidden_fields"])
    for field_name in frontmatter:
        if field_name in forbidden:
            result.errors.append(
                f"Forbidden legacy field detected: '{field_name}'"
            )
            result.passed = False
        elif field_name not in allowed:
            result.errors.append(
                f"Unknown frontmatter field detected: '{field_name}'"
            )
            result.passed = False


def check_single_h1(
    result: ValidationResult, frontmatter: Optional[dict], body: str, file_path: Path, config: dict
) -> None:
    prose = re.sub(
        r"^```.*$\n.*?\n^```$", "", body,
        flags=re.MULTILINE | re.DOTALL
    )
    h1_matches = re.findall(r"^# .+$", prose, re.MULTILINE)
    if len(h1_matches) == 0:
        result.errors.append("Missing H1 heading")
        result.passed = False
    elif len(h1_matches) > 1:
        result.errors.append(
            f"Multiple H1 headings found ({len(h1_matches)}). Expected exactly one."
        )
        result.passed = False


def check_no_inline_metadata(
    result: ValidationResult, frontmatter: Optional[dict], body: str, file_path: Path, config: dict
) -> None:
    prose = re.sub(r"```[\s\S]*?```", "", body)
    prose = re.sub(r"\|[^|\n]+\|[^|\n]+\|", "", prose)
    for pattern in INLINE_METADATA_PATTERNS:
        if re.search(pattern, prose, re.MULTILINE | re.IGNORECASE):
            result.errors.append(f"Inline metadata detected (pattern: {pattern})")
            result.passed = False
            break


def check_workflow_has_trigger(
    result: ValidationResult, frontmatter: Optional[dict], body: str, file_path: Path, config: dict
) -> None:
    if not frontmatter or frontmatter.get("type") != "workflow":
        return
    if "trigger" not in frontmatter:
        result.errors.append("Workflow documents must have 'trigger' field")
        result.passed = False


def check_workflow_has_timeout(
    result: ValidationResult, frontmatter: Optional[dict], body: str, file_path: Path, config: dict
) -> None:
    if not frontmatter or frontmatter.get("type") != "workflow":
        return
    if "timeout" not in frontmatter:
        result.errors.append("Workflow documents must have 'timeout' field")
        result.passed = False


def check_mandatory_sections(
    result: ValidationResult, frontmatter: Optional[dict], body: str, file_path: Path, config: dict
) -> None:
    if not frontmatter:
        return
    if is_exempt_file(file_path, config):
        return
    doc_type = frontmatter.get("type")
    if not doc_type:
        return
    type_config = config["types"].get(doc_type)
    if not type_config:
        return
    required = type_config.get("sections", [])
    if not required:
        return
    present_sections = _extract_all_section_names(body)
    present_ordered = [s for s in present_sections if s in required]
    missing = [sec for sec in required if sec not in present_sections]
    if missing:
        result.errors.append(
            f"Missing mandatory sections for type '{doc_type}': "
            f"expected {required}, found {present_ordered}, "
            f"missing {missing}"
        )
        result.passed = False


def check_section_order(
    result: ValidationResult, frontmatter: Optional[dict], body: str, file_path: Path, config: dict
) -> None:
    if not frontmatter:
        return
    if is_exempt_file(file_path, config):
        return
    doc_type = frontmatter.get("type")
    if not doc_type:
        return
    type_config = config["types"].get(doc_type)
    if not type_config:
        return
    expected_order = type_config.get("sections", [])
    if not expected_order:
        return
    present_sections = _extract_all_section_names(body)
    relevant = [s for s in present_sections if s in expected_order]
    indices = {}
    for idx, sec in enumerate(relevant):
        if sec not in indices:
            indices[sec] = idx
    for i in range(len(expected_order) - 1):
        s1, s2 = expected_order[i], expected_order[i + 1]
        if s1 in indices and s2 in indices and indices[s1] > indices[s2]:
            order_types_block = {"workflow", "contract"}
            if doc_type in order_types_block:
                result.errors.append(
                    f"Section order violation for type '{doc_type}': "
                    f"'## {s1.title()}' must appear before '## {s2.title()}'"
                )
                result.passed = False
            else:
                result.warnings.append(
                    f"Section order advisory for type '{doc_type}': "
                    f"'## {s1.title()}' should appear before '## {s2.title()}'"
                )
            return


def check_no_banned_words(
    result: ValidationResult, frontmatter: Optional[dict], body: str, file_path: Path, config: dict
) -> None:
    non_normative = set(config["non_normative_sections"])

    body_for_split = _blank_code_blocks(body)
    section_pattern = re.compile(r"^## (.+)$", re.MULTILINE)
    section_starts = [
        (m.start(), m.group(1).strip()) for m in section_pattern.finditer(body_for_split)
    ]

    chunks: list[tuple[Optional[str], str]] = []
    if section_starts:
        pre = body_for_split[:section_starts[0][0]]
        if pre.strip():
            chunks.append((None, pre))
        for i, (start, name) in enumerate(section_starts):
            end = section_starts[i + 1][0] if i + 1 < len(section_starts) else len(body_for_split)
            chunks.append((name.upper(), body_for_split[start:end]))
    else:
        chunks.append((None, body_for_split))

    # All banned words are universal — enforced at all tiers
    banned_patterns = list(UNIVERSAL_BANNED_WORDS)

    banned_errors: list[str] = []
    banned_warnings: list[str] = []

    for section_name, text in chunks:
        prose = _clean_prose(text)
        found = []
        for pattern in banned_patterns:
            matches = re.findall(pattern, prose, re.IGNORECASE)
            if matches:
                found.extend(matches)
        if not found:
            continue
        unique = sorted({w.lower() for w in found})
        msg = f"Banned words in section '{section_name}': {', '.join(unique[:5])}"
        if section_name in non_normative:
            banned_warnings.append(msg)
        else:
            banned_errors.append(msg)

    if banned_errors:
        for msg in banned_errors:
            result.errors.append(msg)
        result.passed = False
    for msg in banned_warnings:
        result.warnings.append(msg)


def check_project_terminology(
    result: ValidationResult, frontmatter: Optional[dict], body: str, file_path: Path, config: dict
) -> None:
    rules = config.get("project_banned_words", [])
    if not rules:
        return
    prose = _clean_prose(_blank_code_blocks(body))
    findings = []
    for rule in rules:
        pattern = rule.get("pattern", "")
        if not pattern:
            continue
        if re.search(pattern, prose, re.IGNORECASE):
            findings.append(f"{rule['label']} — {rule.get('suggestion', '')}")
    for finding in dict.fromkeys(findings):
        result.warnings.append(f"Project terminology warning: {finding}")


def check_source_of_truth_valid(
    result: ValidationResult, frontmatter: Optional[dict], body: str, file_path: Path, config: dict
) -> None:
    if not frontmatter or "source_of_truth" not in frontmatter:
        return
    value = frontmatter["source_of_truth"]
    if not isinstance(value, bool):
        result.errors.append(
            f"Field 'source_of_truth' must be a boolean (true/false), got: {value!r}"
        )
        result.passed = False
        return
    if value is False:
        upstream = frontmatter.get("upstream")
        if not upstream:
            result.errors.append(
                "source_of_truth: false requires non-empty 'upstream' "
                "(must point to the authoritative source)"
            )
            result.passed = False


def check_ttl_exceeded(
    result: ValidationResult, frontmatter: Optional[dict], body: str, file_path: Path, config: dict
) -> None:
    if not frontmatter:
        return
    last_verified = frontmatter.get("last_verified")
    ttl_days = frontmatter.get("ttl_days", 90)
    if not last_verified:
        return  # check_no_verification_date handles missing case
    try:
        if isinstance(last_verified, str):
            last_verified_date = datetime.strptime(last_verified, "%Y-%m-%d")
        else:
            last_verified_date = datetime.combine(last_verified, datetime.min.time())
        days_since = (datetime.now() - last_verified_date).days
        if ttl_days == "∞":
            return
        ttl_int = int(ttl_days) if not isinstance(ttl_days, (int, float)) else int(ttl_days)
        if ttl_int == 0:
            return  # Permanent documents (ttl_days=0) do not expire
        if days_since > ttl_int:
            result.warnings.append(
                f"TTL exceeded: {days_since} days since verification (TTL: {ttl_int})"
            )
    except (ValueError, TypeError) as e:
        result.warnings.append(f"Invalid last_verified date format: {last_verified} ({e})")


def check_no_verification_date(
    result: ValidationResult, frontmatter: Optional[dict], body: str, file_path: Path, config: dict
) -> None:
    if frontmatter and isinstance(frontmatter, dict) and "last_verified" not in frontmatter:
        result.errors.append("Missing required field: last_verified")
        result.passed = False


def check_duplicate_doc_id(
    result: ValidationResult, frontmatter: Optional[dict], body: str, file_path: Path, config: dict
) -> None:
    global _doc_id_registry
    if not frontmatter:
        return
    doc_id = frontmatter.get("doc_id")
    if not doc_id:
        return
    if doc_id in _doc_id_registry:
        result.errors.append(
            f"Duplicate doc_id '{doc_id}' — first occurrence in {_doc_id_registry[doc_id]}"
        )
    else:
        _doc_id_registry[doc_id] = str(file_path)


def check_future_dates(
    result: ValidationResult, frontmatter: Optional[dict], body: str, file_path: Path, config: dict
) -> None:
    today = date.today()
    if frontmatter:
        last_verified = frontmatter.get("last_verified")
        if last_verified and isinstance(last_verified, str) and len(last_verified) == 10:
            try:
                dt = datetime.strptime(last_verified, "%Y-%m-%d").date()
                if dt > today:
                    result.warnings.append(f"last_verified is in the future: {last_verified}")
            except ValueError:
                pass
    future_pattern = re.compile(r"20[2-9]\d-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])")
    for match in future_pattern.finditer(body):
        dt_str = match.group()
        try:
            dt_date = datetime.strptime(dt_str, "%Y-%m-%d").date()
            if dt_date > today:
                result.warnings.append(f"Future date in body: {dt_str}")
                break
        except ValueError:
            pass


def check_root_file_integrity(
    result: ValidationResult, frontmatter: Optional[dict], body: str, file_path: Path, config: dict
) -> None:
    if file_path.parent != Path("."):
        return
    filename = file_path.name
    root_config = config.get("root_files", {}).get(filename)
    if not root_config:
        return

    if not frontmatter:
        result.errors.append(f"{filename}: Missing YAML frontmatter")
        result.passed = False
        return

    # Required fields
    required_fields = root_config.get("required_fields", [])
    missing_fields = [f for f in required_fields if f not in frontmatter]
    if missing_fields:
        result.errors.append(
            f"{filename}: Missing required fields: {', '.join(missing_fields)}"
        )
        result.passed = False

    # Type check
    expected_type = root_config.get("required_type")
    if expected_type and frontmatter.get("type") != expected_type:
        result.errors.append(
            f"{filename}: type must be '{expected_type}', "
            f"got '{frontmatter.get('type')}'"
        )
        result.passed = False

    # Size checks
    lines = body.count("\n") + 1
    min_lines = root_config.get("min_line_count", 0)
    max_lines = root_config.get("max_line_count", 999999)
    if lines < min_lines:
        result.errors.append(
            f"{filename}: Too small ({lines} lines, minimum {min_lines})"
        )
        result.passed = False
    if lines > max_lines:
        result.errors.append(
            f"{filename}: Too large ({lines} lines, maximum {max_lines}). "
            f"Consider splitting into smaller documents."
        )
        result.passed = False

    # Required sections
    required_sections = root_config.get("required_sections", [])
    if required_sections:
        present_sections = _extract_all_section_names(body)
        missing = [
            s for s in required_sections
            if not any(s in ps for ps in present_sections)
        ]
        if missing:
            result.errors.append(
                f"{filename}: Missing mandatory sections: {', '.join(missing)}"
            )
            result.passed = False

    # Required pattern in body
    requires_pattern = root_config.get("requires_pattern")
    if requires_pattern and not re.search(requires_pattern, body, re.MULTILINE):
        result.errors.append(f"{filename}: Must contain pattern: {requires_pattern}")
        result.passed = False


def check_doc_kind_consistency(
    result: ValidationResult, frontmatter: Optional[dict], body: str, file_path: Path, config: dict
) -> None:
    if not frontmatter:
        return
    doc_kind = frontmatter.get("doc_kind", "atomic")
    source_of_truth = frontmatter.get("source_of_truth", True)
    if doc_kind != "atomic" and source_of_truth is not False:
        result.errors.append(
            f"doc_kind is '{doc_kind}' — source_of_truth MUST be false for non-atomic documents"
        )
        result.passed = False
    derived_from = frontmatter.get("derived_from")
    if doc_kind != "atomic" and not derived_from:
        result.errors.append(
            f"doc_kind is '{doc_kind}' — derived_from is required for non-atomic documents"
        )
        result.passed = False


def check_glossary_terms_format(
    result: ValidationResult, frontmatter: Optional[dict], body: str, file_path: Path, config: dict
) -> None:
    if not frontmatter:
        return
    glossary_terms = frontmatter.get("glossary_terms")
    if glossary_terms is None:
        return
    if not isinstance(glossary_terms, list):
        result.errors.append("glossary_terms must be a list of term keys")
        result.passed = False


def check_rigor_tier_valid(
    result: ValidationResult, frontmatter: Optional[dict], body: str, file_path: Path, config: dict
) -> None:
    if not frontmatter or "rigor_tier" not in frontmatter:
        return
    rigor_tier = frontmatter["rigor_tier"]
    if rigor_tier not in config.get("rigor_tier_values", ["L0", "L1", "L2", "L3"]):
        result.errors.append(
            f"Invalid rigor_tier: '{rigor_tier}' (valid: L0, L1, L2, L3)"
        )
        result.passed = False


def check_balanced_fences(
    result: ValidationResult, frontmatter: Optional[dict], body: str, file_path: Path, config: dict
) -> None:
    fences = re.findall(r"```", body)
    if len(fences) % 2 != 0:
        result.warnings.append(
            f"Unbalanced code fences ({len(fences)} ``` markers) — "
            "section parsing may be unreliable; fix stray ``` in document"
        )


# ---------------------------------------------------------------------------
# Fitness calculation
# ---------------------------------------------------------------------------

def calculate_fitness_score(
    result: ValidationResult, frontmatter: Optional[dict]
) -> float:
    """Fitness score is CI-only telemetry. The validator does not compute it.

    Actual fitness computation runs in the homeostasis scan (CI cron),
    using the algorithm defined in Section 6.1 of the standard.
    Frontmatter MUST NOT contain a fitness_score field.
    """
    return 0.0


# ---------------------------------------------------------------------------
# Baseline support
# ---------------------------------------------------------------------------

def load_baseline(path: Optional[Path]) -> dict[str, dict[str, list[str]]]:
    if not path or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload.get("files", {})


def write_baseline(path: Path, results: list[ValidationResult]) -> None:
    payload = {
        "version": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "files": {
            result.file_path: {
                "errors": result.errors,
                "warnings": result.warnings,
            }
            for result in results
            if result.errors or result.warnings
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def apply_baseline(
    result: ValidationResult, baseline: dict[str, dict[str, list[str]]]
) -> None:
    entry = baseline.get(result.file_path)
    if not entry:
        result.fitness_score = calculate_fitness_score(result, None)
        return
    error_allow = set(entry.get("errors", []))
    warning_allow = set(entry.get("warnings", []))
    original_errors = list(result.errors)
    original_warnings = list(result.warnings)
    result.errors = [m for m in result.errors if m not in error_allow]
    result.warnings = [m for m in result.warnings if m not in warning_allow]
    result.suppressed_errors = len(original_errors) - len(result.errors)
    result.suppressed_warnings = len(original_warnings) - len(result.warnings)
    result.passed = len(result.errors) == 0


# ---------------------------------------------------------------------------
# Check registry
# ---------------------------------------------------------------------------

def _make_check_registry(config: dict) -> list[tuple[str, str, Callable]]:
    """Build the check registry using the given config."""
    return [
        ("frontmatter_present", "error", check_frontmatter_present),
        ("description_exists", "error", check_description_exists),
        ("doc_id_format", "error", check_doc_id_format),
        ("type_valid", "error", check_type_valid),
        ("status_valid", "error", check_status_valid),
        ("rigor_tier_valid", "error", check_rigor_tier_valid),
        ("ttl_days_integer", "error", check_ttl_days_integer),
        ("ai_scope_valid", "error", check_ai_scope_valid),
        ("stability_valid", "error", check_stability_valid),
        ("strict_frontmatter", "error", check_strict_frontmatter),
        ("single_h1", "error", check_single_h1),
        ("no_inline_metadata", "error", check_no_inline_metadata),
        ("workflow_has_trigger", "error", check_workflow_has_trigger),
        ("workflow_has_timeout", "error", check_workflow_has_timeout),
        ("mandatory_sections", "error", check_mandatory_sections),
        ("section_order", "error", check_section_order),
        ("no_banned_words", "error", check_no_banned_words),
        ("source_of_truth_valid", "error", check_source_of_truth_valid),
        ("doc_kind_consistency", "error", check_doc_kind_consistency),
        ("glossary_terms_format", "error", check_glossary_terms_format),
        ("root_file_integrity", "error", check_root_file_integrity),
        ("duplicate_doc_id", "error", check_duplicate_doc_id),
        ("no_verification_date", "error", check_no_verification_date),
        ("ttl_exceeded", "warning", check_ttl_exceeded),
        ("future_dates", "warning", check_future_dates),
        ("project_terminology", "warning", check_project_terminology),
        ("balanced_fences", "warning", check_balanced_fences),
    ]


# ---------------------------------------------------------------------------
# File validation
# ---------------------------------------------------------------------------

def validate_file(file_path: Path, config: dict, check_registry: list) -> ValidationResult:
    result = ValidationResult(file_path=str(file_path))

    # Skip excluded directories
    path_str = str(file_path)
    for excluded in config.get("excluded_dirs", []):
        if f"/{excluded}/" in path_str or f"{excluded}/" in path_str:
            return result

    frontmatter, body = load_markdown_file(file_path)
    if isinstance(body, str) and body.startswith("Could not read file"):
        result.errors.append(body)
        result.passed = False
        return result
    if isinstance(body, str) and body.startswith("Invalid"):
        result.errors.append(body)
        result.passed = False
        return result

    for _, _, check_fn in check_registry:
        check_fn(result, frontmatter, body, file_path, config)

    result.fitness_score = calculate_fitness_score(result, frontmatter)
    return result


def find_markdown_files(paths: list[str]) -> list[Path]:
    files = []
    for path_str in paths:
        path = Path(path_str)
        if path.is_file() and path.suffix == ".md":
            files.append(path)
        elif path.is_dir():
            files.extend(path.rglob("*.md"))
    return files


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="AFDS Documentation Validator"
    )
    parser.add_argument(
        "paths", nargs="*", default=None,
        help="Paths to validate (files or directories)",
    )
    parser.add_argument(
        "--config", default=None,
        help="Path to YAML configuration file",
    )
    parser.add_argument(
        "--pre-commit", action="store_true",
        help="Pre-commit mode (validate specific files)",
    )
    parser.add_argument(
        "--report", action="store_true", help="Output JSON report",
    )
    parser.add_argument(
        "--strict", action="store_true", help="Treat warnings as errors",
    )
    parser.add_argument(
        "--baseline", default=None,
        help="Known-failures baseline path",
    )
    parser.add_argument(
        "--no-baseline", action="store_true",
        help="Ignore the known-failures baseline",
    )
    parser.add_argument(
        "--write-baseline", nargs="?", const=".afds-baseline.json",
        help="Write current findings to a baseline file and exit 0",
    )
    parser.add_argument(
        "--ci", action="store_true",
        help="CI/CD mode: read changed files from CHANGED_FILES env var",
    )

    args = parser.parse_args()

    # Load configuration
    config_path = Path(args.config) if args.config else None
    config = load_config(config_path)

    # Determine baseline path
    if args.baseline:
        baseline_path = Path(args.baseline)
    elif args.no_baseline:
        baseline_path = None
    else:
        baseline_path = Path(config.get("baseline_path", ".afds-baseline.json"))

    # Build check registry
    check_registry = _make_check_registry(config)

    # Find files to validate
    if args.ci:
        changed_files = os.environ.get("CHANGED_FILES", "")
        if changed_files:
            files = [
                Path(f.strip()) for f in changed_files.split()
                if f.strip().endswith(".md")
            ]
        else:
            files = []
        print(f"CI mode: Validating {len(files)} changed markdown files")
    elif args.pre_commit:
        files = [Path(p) for p in (args.paths or []) if p.endswith(".md")]
    else:
        paths = args.paths if args.paths else config.get("default_paths", ["docs/"])
        files = find_markdown_files(paths)

    # Filter excluded paths
    excluded = config.get("excluded_dirs", [])
    files = [
        f for f in files
        if not any(f"/{d}/" in str(f) or f"{d}/" in str(f) for d in excluded)
    ]

    if not files:
        print("No documentation files found to validate.")
        sys.exit(0)

    # Validate
    global _doc_id_registry
    _doc_id_registry = {}

    results = [validate_file(f, config, check_registry) for f in files]

    if args.write_baseline:
        write_baseline(Path(args.write_baseline), results)
        print(f"Wrote baseline: {args.write_baseline}")
        sys.exit(0)

    baseline = {} if args.no_baseline or not baseline_path else load_baseline(baseline_path)
    for result in results:
        apply_baseline(result, baseline)
        fm, _ = load_markdown_file(Path(result.file_path))
        result.fitness_score = calculate_fitness_score(
            result, fm if isinstance(fm, dict) else None
        )

    # Report
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)
    warnings = sum(len(r.warnings) for r in results)
    suppressed_errors = sum(r.suppressed_errors for r in results)
    suppressed_warnings = sum(r.suppressed_warnings for r in results)

    if args.report:
        report = {
            "total": len(results),
            "passed": passed,
            "failed": failed,
            "warnings": warnings,
            "suppressed_errors": suppressed_errors,
            "suppressed_warnings": suppressed_warnings,
            "results": [
                {
                    "file": r.file_path,
                    "passed": r.passed,
                    "errors": r.errors,
                    "warnings": r.warnings,
                    "fitness_score": r.fitness_score,
                    "suppressed_errors": r.suppressed_errors,
                    "suppressed_warnings": r.suppressed_warnings,
                }
                for r in results
            ],
        }
        print(json.dumps(report, indent=2))
    else:
        print(f"\n{'=' * 60}")
        print("AFDS DOCUMENTATION VALIDATION")
        print(f"{'=' * 60}")
        print(f"Files checked: {len(results)}")
        print(f"Passed: {passed}")
        print(f"Failed: {failed}")
        print(f"Warnings: {warnings}")
        if not args.no_baseline and baseline_path and baseline:
            if suppressed_errors or suppressed_warnings:
                print(
                    f"Suppressed by baseline: {suppressed_errors} errors, "
                    f"{suppressed_warnings} warnings"
                )
        print(f"{'=' * 60}\n")

        for result in results:
            if not result.passed:
                print(f"FAIL  {result.file_path}")
                for error in result.errors:
                    print(f"   • {error}")
                print()

        for result in results:
            if result.warnings:
                print(f"WARN  {result.file_path}")
                for warning in result.warnings:
                    print(f"   • {warning}")
                print()

    if failed > 0 or (args.strict and warnings > 0):
        if not args.report:
            print("FAIL  Validation FAILED")
        sys.exit(1)
    else:
        if not args.report:
            print("PASS  Validation PASSED")
        sys.exit(0)


if __name__ == "__main__":
    main()
