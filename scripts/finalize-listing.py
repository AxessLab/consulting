#!/usr/bin/env python3
"""Format AI-curated matches into Slack output and listing memory."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from assignment_matching import MatchedAssignment, format_slack_line, parse_client_label, parse_hours_label
from assignment_platforms import AssignmentRecord
from listing_memory import DEFAULT_MEMORY_PATH, commit_memory


SECTION_ORDER = ("accessibility_specialist", "other_a11y_mentions", "other")
SECTION_TITLES = {
    "accessibility_specialist": "*1. Accessibility specialist related roles*",
    "other_a11y_mentions": "*2. Other roles mentioning accessibility related terms*",
    "other": "*3. Other roles where accessibility is not mentioned*",
}


def load_candidates(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_curated(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def assignment_index(candidates: dict[str, Any]) -> dict[str, AssignmentRecord]:
    index: dict[str, AssignmentRecord] = {}
    for row in candidates.get("assignments", []):
        record = AssignmentRecord(**row)
        index[record.dedupe_key] = record
        index[f"{record.platform}:{record.listing_id}"] = record
        index[record.listing_id] = record
    return index


def resolve_assignment(
    item: dict[str, Any],
    index: dict[str, AssignmentRecord],
) -> AssignmentRecord:
    dedupe_key = item.get("dedupe_key")
    if dedupe_key and dedupe_key in index:
        return index[dedupe_key]

    listing_id = item.get("listing_id")
    platform = item.get("platform")
    if listing_id and platform:
        key = f"{platform}:{listing_id}"
        if key in index:
            return index[key]
    if listing_id and listing_id in index:
        return index[listing_id]

    raise KeyError(
        f"Could not resolve assignment for curated item: {item!r}. "
        "Use dedupe_key from listing-candidates.json."
    )


def build_slack_main(
    reported: list[MatchedAssignment],
    scan_date: date,
) -> str:
    parts: list[str] = []
    for section in SECTION_ORDER:
        parts.append(SECTION_TITLES[section])
        section_matches = [match for match in reported if match.section == section]
        if not section_matches:
            parts.append("No new matches.")
        else:
            parts.extend(format_slack_line(match, scan_date) for match in section_matches)
        parts.append("")
    return "\n".join(parts).strip()


def build_slack_debug(
    *,
    candidates: dict[str, Any],
    curated: dict[str, Any],
    reported_count: int,
) -> str:
    stats = candidates.get("stats", {})
    lines = [
        candidates.get("platform_summary", "Scanned platforms: (unknown)"),
        f"Scan date: {candidates.get('scan_date', '')}",
        (
            "Visible assignments: "
            f"{stats.get('total_visible', 0)} "
            f"(unique after cross-platform dedupe: {stats.get('total_unique_visible', 0)})"
        ),
        f"New ids: {stats.get('new_ids', 0)}",
        f"Reported matches: {reported_count}",
        f"Script suggestions (heuristic): {stats.get('script_suggestions', 0)}",
        "",
        "Close non-matches (sample):",
    ]

    rejects = curated.get("debug_rejects") or []
    if not rejects:
        lines.append("- none")
    else:
        for item in rejects[:25]:
            consultants = item.get("would_match") or []
            suffix = f" | would match: {', '.join(consultants)}" if consultants else ""
            listing_id = item.get("listing_id", item.get("id", "?"))
            platform = item.get("platform", "")
            platform_suffix = f" [{platform}]" if platform else ""
            lines.append(
                f"- {listing_id}{platform_suffix} | {item.get('title', '?')} | "
                f"{item.get('reason', 'rejected')}{suffix}"
            )
        if len(rejects) > 25:
            lines.append(f"... and {len(rejects) - 25} more rejected items")

    review_notes = curated.get("review_notes")
    if review_notes:
        lines.extend(["", "Review notes:", review_notes])

    return "\n".join(lines)


def finalize_listing(
    candidates_path: Path,
    curated_path: Path,
) -> dict[str, Any]:
    candidates = load_candidates(candidates_path)
    curated = load_curated(curated_path)
    index = assignment_index(candidates)
    scan_date = date.fromisoformat(candidates["scan_date"])

    reported: list[MatchedAssignment] = []
    for item in curated.get("reported", []):
        assignment = resolve_assignment(item, index)
        consultants = item.get("consultants") or []
        if not consultants:
            raise ValueError(f"Curated item missing consultants: {item!r}")
        section = item.get("section")
        if section not in SECTION_ORDER:
            raise ValueError(f"Invalid section {section!r} in curated item {item!r}")
        reported.append(
            MatchedAssignment(
                assignment=assignment,
                section=section,
                consultants=consultants,
                hours_label=parse_hours_label(assignment),
                client_label=parse_client_label(assignment),
            )
        )

    slack_main = build_slack_main(reported, scan_date)
    slack_debug = build_slack_debug(
        candidates=candidates,
        curated=curated,
        reported_count=len(reported),
    )

    return {
        "source": "curated-listing",
        "scan_date": candidates["scan_date"],
        "memory_path": candidates.get("memory_path"),
        "platforms": candidates.get("platforms", []),
        "platform_results": candidates.get("platform_results", []),
        "stats": {
            **candidates.get("stats", {}),
            "reported_matches": len(reported),
        },
        "slack_main": slack_main,
        "slack_debug": slack_debug,
        "memory_update": candidates.get("memory_update"),
        "matches": [
            {
                "listing_id": match.assignment.listing_id,
                "platform": match.assignment.platform,
                "section": match.section,
                "title": match.assignment.title,
                "consultants": match.consultants,
                "source_url": match.assignment.source_url,
            }
            for match in reported
        ],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "candidates",
        nargs="?",
        type=Path,
        help="listing-candidates.json from fetch-assignments.py",
    )
    parser.add_argument(
        "curated",
        nargs="?",
        type=Path,
        help="curated-listing.json written by the automation agent",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Write listing-output.json (default: stdout)",
    )
    parser.add_argument(
        "--memory-path",
        type=Path,
        default=DEFAULT_MEMORY_PATH,
        help="Path to persistent seen-id memory file",
    )
    parser.add_argument(
        "--commit-memory",
        type=Path,
        metavar="LISTING_JSON",
        help="Update seen-id memory from a previous listing JSON output",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.commit_memory:
        commit_memory(args.commit_memory, args.memory_path)
        return 0

    if not args.candidates or not args.curated:
        raise SystemExit("candidates and curated JSON paths are required unless using --commit-memory")

    payload = finalize_listing(args.candidates, args.curated)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
