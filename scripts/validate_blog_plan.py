#!/usr/bin/env python3
"""Validate the blog approval packet without publishing content."""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
BLOG_DIR = ROOT / "website" / "content" / "blog"
FIRST_COMMIT_DATE = "2026-03-30"

EXPECTED_BATCH_COUNTS = {
    "launch": 16,
    "batch-2": 8,
    "batch-3": 8,
    "batch-4": 6,
    "batch-5": 11,
}

PLACEHOLDER_FILES = {
    "62-simulations-retrospective.mdx",
    "agent-dreams.mdx",
    "conversation-engine-deep-dive.mdx",
    "designing-memory-for-agents.mdx",
    "economics-of-artificial-life.mdx",
    "eval-framework.mdx",
    "first-week-lessons.mdx",
    "multi-model-matters.mdx",
    "the-management-problem.mdx",
    "what-we-got-wrong.mdx",
    "who-talks-next.mdx",
    "why-a-reality-show-for-ai.mdx",
    "why-agi-is-tongue-in-cheek.mdx",
    "why-ai-agents-are-reactive.mdx",
}


def read_text(path: Path) -> str:
    if not path.exists():
        raise AssertionError(f"Missing required file: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def load_manifest() -> list[dict[str, str]]:
    path = DOCS / "BLOG-SERIES-MANIFEST.tsv"
    if not path.exists():
        raise AssertionError("Missing docs/BLOG-SERIES-MANIFEST.tsv")
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def validate_manifest(rows: list[dict[str, str]]) -> list[str]:
    messages: list[str] = []
    required_fields = ["order", "batch", "date", "slug", "title", "angle"]
    if not rows:
        raise AssertionError("Manifest is empty")
    if list(rows[0].keys()) != required_fields:
        raise AssertionError("Manifest header does not match expected fields")
    if len(rows) != 49:
        raise AssertionError(f"Expected 49 manifest rows, found {len(rows)}")

    slugs: Counter[str] = Counter()
    batches: Counter[str] = Counter()
    for index, row in enumerate(rows, start=1):
        order = int(row["order"])
        if order != index:
            raise AssertionError(f"Manifest order mismatch: row {index} has {order}")
        if row["date"] < FIRST_COMMIT_DATE:
            raise AssertionError(
                f"Post {row['slug']} is dated before first commit: {row['date']}"
            )
        slugs[row["slug"]] += 1
        batches[row["batch"]] += 1

    duplicate_slugs = [slug for slug, count in slugs.items() if count > 1]
    if duplicate_slugs:
        raise AssertionError(f"Duplicate manifest slugs: {', '.join(duplicate_slugs)}")
    for batch, expected_count in EXPECTED_BATCH_COUNTS.items():
        found = batches[batch]
        if found != expected_count:
            raise AssertionError(
                f"Expected {expected_count} rows for {batch}, found {found}"
            )
    messages.append("manifest: 49 rows, sequential order, unique slugs, valid batches")
    return messages


def count_between(text: str, start: str, end: str, pattern: str) -> int:
    start_index = text.index(start)
    end_index = text.index(end, start_index)
    section = text[start_index:end_index]
    return len(re.findall(pattern, section, flags=re.MULTILINE))


def validate_docs() -> list[str]:
    messages: list[str] = []
    editorial = read_text(DOCS / "BLOG-EDITORIAL-PLAN.md")
    approval = read_text(DOCS / "BLOG-APPROVAL-SUMMARY.md")
    checklist = read_text(DOCS / "BLOG-IMPLEMENTATION-CHECKLIST.md")
    dossiers = read_text(DOCS / "BLOG-LAUNCH-DOSSIERS.md")
    replacement_audit = read_text(DOCS / "BLOG-PLACEHOLDER-REPLACEMENT-AUDIT.md")
    evidence_ledger = read_text(DOCS / "BLOG-EVIDENCE-LEDGER.md")
    writing_playbook = read_text(DOCS / "BLOG-WRITING-PLAYBOOK.md")

    plan_count = count_between(
        editorial,
        "## Proposed Replacement Series",
        "## Launch Batch Recommendation",
        r"^\| 2026-",
    )
    if plan_count != 49:
        raise AssertionError(f"Expected 49 editorial plan rows, found {plan_count}")

    approval_count = count_between(
        approval,
        "## Launch Batch To Draft After Approval",
        "## Deferred Batches",
        r"^\| [0-9]+ \|",
    )
    if approval_count != 16:
        raise AssertionError(f"Expected 16 approval launch rows, found {approval_count}")

    checklist_launch_count = count_between(
        checklist,
        "## Files To Create For Recommended Launch",
        "## Placeholder Files To Remove Or Redirect",
        r"^\| [0-9]+ \|",
    )
    if checklist_launch_count != 16:
        raise AssertionError(
            f"Expected 16 implementation checklist launch rows, found {checklist_launch_count}"
        )

    placeholder_count = count_between(
        checklist,
        "## Placeholder Files To Remove Or Redirect",
        "Recommended launch behavior",
        r"^- `",
    )
    if placeholder_count != 14:
        raise AssertionError(
            f"Expected 14 implementation checklist placeholder rows, found {placeholder_count}"
        )

    dossier_count = len(re.findall(r"^## [0-9]+\. `", dossiers, flags=re.MULTILINE))
    if dossier_count != 16:
        raise AssertionError(f"Expected 16 launch dossiers, found {dossier_count}")

    audit_count = len(
        re.findall(r"^\| `.*\.mdx` \|", replacement_audit, flags=re.MULTILINE)
    )
    if audit_count != 14:
        raise AssertionError(f"Expected 14 placeholder audit rows, found {audit_count}")

    for name, text in {
        "approval summary": approval,
        "evidence ledger": evidence_ledger,
        "launch dossiers": dossiers,
        "placeholder audit": replacement_audit,
        "implementation checklist": checklist,
        "writing playbook": writing_playbook,
    }.items():
        if "website/content/blog/" in text and "approval" not in text.lower():
            raise AssertionError(f"{name} references blog edits without approval boundary")

    messages.append("docs: plan, approval, checklist, dossiers, and audit counts match")
    return messages


def validate_blog_dir(rows: list[dict[str, str]], mode: str) -> list[str]:
    messages: list[str] = []
    current_files = {path.name for path in BLOG_DIR.glob("*.mdx")}
    launch_files = {f"{row['slug']}.mdx" for row in rows if row["batch"] == "launch"}
    all_files = {f"{row['slug']}.mdx" for row in rows}

    if mode == "planning":
        if current_files != PLACEHOLDER_FILES:
            missing = sorted(PLACEHOLDER_FILES - current_files)
            extra = sorted(current_files - PLACEHOLDER_FILES)
            raise AssertionError(
                f"Planning mode expects original placeholder files. Missing={missing}; extra={extra}"
            )
        messages.append("blog dir: original 14 placeholder MDX files are still untouched")
    elif mode == "launch":
        if current_files != launch_files:
            missing = sorted(launch_files - current_files)
            extra = sorted(current_files - launch_files)
            raise AssertionError(
                f"Launch mode expects 16 launch files only. Missing={missing}; extra={extra}"
            )
        messages.append("blog dir: recommended 16 launch MDX files are present")
    elif mode == "all":
        if current_files != all_files:
            missing = sorted(all_files - current_files)
            extra = sorted(current_files - all_files)
            raise AssertionError(
                f"All mode expects all 49 manifest files only. Missing={missing}; extra={extra}"
            )
        expected_by_slug = {row["slug"]: row for row in rows}
        for path in BLOG_DIR.glob("*.mdx"):
            slug = path.stem
            raw = path.read_text(encoding="utf-8")
            expected = expected_by_slug[slug]
            required = {
                "title": expected["title"],
                "date": expected["date"],
                "author": "Brad Taylor",
            }
            for key, value in required.items():
                if f'{key}: "{value}"' not in raw:
                    raise AssertionError(
                        f"{path.name} is missing expected frontmatter {key}: {value}"
                    )
            if "tags: [" not in raw:
                raise AssertionError(f"{path.name} is missing tags frontmatter")
            evidence_match = re.search(
                r"^## Evidence\n\n(?P<evidence>.*?)(?=^## What Broke)",
                raw,
                flags=re.MULTILINE | re.DOTALL,
            )
            if not evidence_match:
                raise AssertionError(f"{path.name} is missing an Evidence section")
            evidence_count = len(
                re.findall(r"^- ", evidence_match.group("evidence"), flags=re.MULTILINE)
            )
            if evidence_count < 3:
                raise AssertionError(
                    f"{path.name} does not appear to include at least three evidence anchors"
                )
        messages.append("blog dir: all 49 approved MDX files are present")
    else:
        raise AssertionError(f"Unknown mode: {mode}")

    return messages


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=["planning", "launch", "all"],
        default="planning",
        help=(
            "planning validates the pre-approval state; launch validates the 16-post "
            "launch state; all validates the approved 49-post state"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        rows = load_manifest()
        messages = []
        messages.extend(validate_manifest(rows))
        messages.extend(validate_docs())
        messages.extend(validate_blog_dir(rows, args.mode))
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    for message in messages:
        print(f"OK: {message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
