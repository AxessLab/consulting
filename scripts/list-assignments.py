#!/usr/bin/env python3
"""Deterministic listing (debug only). Prefer fetch-assignments.py + AI curation."""

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

from assignment_matching import (
    MatchedAssignment,
    cross_platform_dedupe,
    format_slack_line,
    load_consultant_profiles,
    process_assignments,
)
from assignment_platforms import DEFAULT_PLATFORMS, AssignmentRecord, PlatformScanResult, scan_platforms
from listing_memory import DEFAULT_MEMORY_PATH, build_memory_payload, commit_memory, load_memory


def section_lines(matches: list[MatchedAssignment], section: str, scan_date: date) -> str:
    section_matches = [match for match in matches if match.section == section]
    if not section_matches:
        return "No new matches."
    return "\n\n".join(format_slack_line(match, scan_date) for match in section_matches)


def build_slack_main(matches: list[MatchedAssignment], scan_date: date) -> str:
    parts = [
        "*1. Accessibility specialist related roles*",
        section_lines(matches, "accessibility_specialist", scan_date),
        "",
        "*2. Other roles mentioning accessibility related terms*",
        section_lines(matches, "other_a11y_mentions", scan_date),
        "",
        "*3. Other roles where accessibility is not mentioned*",
        section_lines(matches, "other", scan_date),
    ]
    return "\n".join(parts).strip()


def build_platform_summary(platform_results: list[PlatformScanResult]) -> str:
    parts: list[str] = []
    for result in platform_results:
        if result.status == "ok":
            parts.append(f"{result.platform} ({result.count})")
        elif result.status == "skipped":
            parts.append(f"{result.platform} (skipped)")
        else:
            parts.append(f"{result.platform} (error)")
    return "Scanned platforms: " + ", ".join(parts)


def build_slack_debug(
    *,
    scan_date: date,
    platform_results: list[PlatformScanResult],
    total_visible: int,
    total_unique_visible: int,
    new_count: int,
    reported_count: int,
    rejects: list[dict[str, Any]],
) -> str:
    lines = [
        build_platform_summary(platform_results),
        f"Scan date: {scan_date.isoformat()}",
        f"Visible assignments: {total_visible} (unique after cross-platform dedupe: {total_unique_visible})",
        f"New ids: {new_count}",
        f"Reported matches: {reported_count}",
        "(deterministic mode — prefer fetch + AI curation for production)",
        "",
        "Close non-matches (sample):",
    ]
    location_rejects = [item for item in rejects if item.get("reason") == "location"]
    other_rejects = [item for item in rejects if item.get("reason") != "location"]

    for item in location_rejects[:15] + other_rejects[:10]:
        consultants = item.get("would_match") or []
        suffix = f" | would match: {', '.join(consultants)}" if consultants else ""
        platform = item.get("platform", "")
        platform_suffix = f" [{platform}]" if platform else ""
        lines.append(
            f"- {item['id']}{platform_suffix} | {item['title']} | {item['reason']}{suffix}"
        )

    if len(rejects) > 25:
        lines.append(f"... and {len(rejects) - 25} more rejected items")
    if not rejects:
        lines.append("- none")
    return "\n".join(lines)


def prepare_listing(
    *,
    memory_path: Path,
    platform_ids: list[str],
    scan_date: date | None = None,
    max_pages: int | None = None,
    headless: bool = True,
) -> dict[str, Any]:
    scan_date = scan_date or date.today()
    seen_keys, _ = load_memory(memory_path)

    raw_assignments, platform_results = scan_platforms(
        platform_ids,
        max_pages=max_pages,
        headless=headless,
    )
    deduped_assignments = cross_platform_dedupe(raw_assignments)
    new_assignments = [
        assignment for assignment in deduped_assignments if assignment.dedupe_key not in seen_keys
    ]

    profiles = load_consultant_profiles()
    matches, rejects = process_assignments(
        new_assignments,
        seen_keys=seen_keys,
        scan_date=scan_date,
        profiles=profiles,
    )

    memory_payload = build_memory_payload(
        assignments=deduped_assignments,
        platform_results=platform_results,
        scan_date=scan_date,
    )

    return {
        "source": "deterministic-listing",
        "scan_date": scan_date.isoformat(),
        "memory_path": str(memory_path),
        "platforms": [result.platform for result in platform_results],
        "platform_results": [
            {
                "platform": result.platform,
                "status": result.status,
                "count": result.count,
                "message": result.message,
            }
            for result in platform_results
        ],
        "stats": {
            "total_visible": len(raw_assignments),
            "total_unique_visible": len(deduped_assignments),
            "previously_seen": len(seen_keys),
            "new_ids": len(new_assignments),
            "reported_matches": len(matches),
            "rejected": len(rejects),
            "active_consultants": len(profiles),
        },
        "slack_main": build_slack_main(matches, scan_date),
        "slack_debug": build_slack_debug(
            scan_date=scan_date,
            platform_results=platform_results,
            total_visible=len(raw_assignments),
            total_unique_visible=len(deduped_assignments),
            new_count=len(new_assignments),
            reported_count=len(matches),
            rejects=rejects,
        ),
        "memory_update": memory_payload,
        "matches": [
            {
                "listing_id": match.assignment.listing_id,
                "platform": match.assignment.platform,
                "section": match.section,
                "title": match.assignment.title,
                "consultants": match.consultants,
                "source_url": match.assignment.source_url,
            }
            for match in matches
        ],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "Production listing uses fetch-assignments.py + AI curation + finalize-listing.py. "
            "Pass --deterministic only for quick heuristic testing."
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Write listing JSON to this file (default: stdout)",
    )
    parser.add_argument(
        "--memory-path",
        type=Path,
        default=DEFAULT_MEMORY_PATH,
        help="Path to persistent seen-id memory file",
    )
    parser.add_argument(
        "--platform",
        action="append",
        dest="platforms",
        choices=DEFAULT_PLATFORMS,
        help="Platform to scan (default: all registered platforms)",
    )
    parser.add_argument(
        "--scan-date",
        type=str,
        help="Override scan date (YYYY-MM-DD) for active-date filtering",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Limit allakonsultuppdrag.se pagination for testing",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run Verama browser login with a visible window",
    )
    parser.add_argument(
        "--deterministic",
        action="store_true",
        help="Run full heuristic filter/match in Python (not for production Slack posting)",
    )
    parser.add_argument(
        "--commit-memory",
        type=Path,
        metavar="LISTING_JSON",
        help="Update seen-id memory from a previous listing JSON output",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    args = parse_args(argv)

    if args.commit_memory:
        commit_memory(args.commit_memory, args.memory_path)
        return 0

    if not args.deterministic:
        print(
            "list-assignments.py no longer posts heuristic matches by default.\n"
            "Use:\n"
            "  python scripts/fetch-assignments.py -o listing-candidates.json\n"
            "  (curate matches — see automation-prompts/assignment-listing.md)\n"
            "  python scripts/finalize-listing.py listing-candidates.json curated-listing.json -o listing-output.json\n"
            "Or pass --deterministic for quick script-only testing.",
            file=sys.stderr,
        )
        return 2

    scan_date = date.fromisoformat(args.scan_date) if args.scan_date else date.today()
    platform_ids = args.platforms or DEFAULT_PLATFORMS
    payload = prepare_listing(
        memory_path=args.memory_path,
        platform_ids=platform_ids,
        scan_date=scan_date,
        max_pages=args.max_pages,
        headless=not args.headed,
    )

    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
