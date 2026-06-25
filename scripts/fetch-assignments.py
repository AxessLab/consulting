#!/usr/bin/env python3
"""Fetch assignments from all platforms, apply dedupe, emit candidates for AI curation."""

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
    cross_platform_dedupe,
    export_consultant_summaries,
    load_consultant_profiles,
    suggest_assignments,
    suggestion_to_dict,
)
from assignment_platforms import DEFAULT_PLATFORMS, AssignmentRecord, scan_platforms
from listing_memory import DEFAULT_MEMORY_PATH, build_memory_payload, collect_seen_ids_by_source, load_memory


def build_platform_summary(platform_results: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for result in platform_results:
        label = result["platform"]
        if result["status"] == "ok":
            parts.append(f"{label} ({result['count']})")
        elif result["status"] == "skipped":
            parts.append(f"{label} (skipped)")
        else:
            parts.append(f"{label} (error)")
    return "Scanned sources: " + ", ".join(parts)


def new_ids_by_source(
    assignments: list[AssignmentRecord],
    memory_data: dict[str, Any],
) -> dict[str, list[str]]:
    seen_by_source = collect_seen_ids_by_source(memory_data)
    ids_by_source: dict[str, set[str]] = {}
    for assignment in assignments:
        source_seen = seen_by_source.get(assignment.source_key, set())
        if assignment.source_id not in source_seen:
            ids_by_source.setdefault(assignment.source_key, set()).add(assignment.source_id)
    return {source: sorted(ids) for source, ids in ids_by_source.items()}


def prepare_candidates(
    *,
    memory_path: Path,
    platform_ids: list[str],
    scan_date: date,
    max_pages: int | None = None,
    headless: bool = True,
    with_suggestions: bool = True,
) -> dict[str, Any]:
    seen_keys, memory_data = load_memory(memory_path)

    raw_assignments, platform_results = scan_platforms(
        platform_ids,
        max_pages=max_pages,
        headless=headless,
    )
    per_source_new_ids = new_ids_by_source(raw_assignments, memory_data)
    new_assignments_before_cross_source_dedupe = [
        assignment
        for assignment in raw_assignments
        if assignment.dedupe_key not in seen_keys
    ]
    report_candidates = cross_platform_dedupe(new_assignments_before_cross_source_dedupe)

    profiles = load_consultant_profiles()
    suggestions: list[dict[str, Any]] = []
    expired: list[dict[str, Any]] = []
    if with_suggestions:
        active_suggestions, expired_suggestions = suggest_assignments(
            report_candidates,
            scan_date=scan_date,
            profiles=profiles,
        )
        suggestions = [suggestion_to_dict(item) for item in active_suggestions]
        expired = [suggestion_to_dict(item) for item in expired_suggestions]

    platform_payload = [
        {
            "platform": result.platform,
            "status": result.status,
            "count": result.count,
            "message": result.message,
        }
        for result in platform_results
    ]

    memory_update = build_memory_payload(
        assignments=raw_assignments,
        platform_results=platform_results,
        scan_date=scan_date,
        previous_memory=memory_data,
    )

    suggested_report = [
        item for item in suggestions if item.get("suggested_section") is not None
    ]

    return {
        "source": "assignment-fetch",
        "scan_date": scan_date.isoformat(),
        "memory_path": str(memory_path),
        "platforms": [result.platform for result in platform_results],
        "platform_results": platform_payload,
        "platform_summary": build_platform_summary(platform_payload),
        "consultants": export_consultant_summaries(profiles),
        "stats": {
            "total_visible": len(raw_assignments),
            "total_unique_visible": len(raw_assignments),
            "cross_source_unique_new_ids": len(report_candidates),
            "previously_seen": len(seen_keys),
            "new_ids": sum(len(ids) for ids in per_source_new_ids.values()),
            "new_ids_by_source": per_source_new_ids,
            "expired_new_ids": len(expired),
            "script_suggestions": len(suggested_report),
            "active_consultants": len(profiles),
        },
        "assignments": [record.to_dict() for record in report_candidates],
        "all_visible_assignments": [record.to_dict() for record in raw_assignments],
        "new_dedupe_keys": [
            assignment.dedupe_key for assignment in new_assignments_before_cross_source_dedupe
        ],
        "report_candidate_dedupe_keys": [assignment.dedupe_key for assignment in report_candidates],
        "suggestions": suggestions,
        "expired": expired,
        "memory_update": memory_update,
        "next_steps": [
            "Review new assignments and script suggestions using automation-prompts/assignment-listing.md",
            "Write curated-listing.json with final reported matches and debug rejects",
            "Run: python scripts/finalize-listing.py listing-candidates.json curated-listing.json -o listing-output.json",
        ],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        required=True,
        help="Write candidate JSON for AI curation",
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
        "--no-suggestions",
        action="store_true",
        help="Skip heuristic match suggestions (fetch + dedupe only)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    args = parse_args(argv)
    scan_date = date.fromisoformat(args.scan_date) if args.scan_date else date.today()
    platform_ids = args.platforms or DEFAULT_PLATFORMS

    payload = prepare_candidates(
        memory_path=args.memory_path,
        platform_ids=platform_ids,
        scan_date=scan_date,
        max_pages=args.max_pages,
        headless=not args.headed,
        with_suggestions=not args.no_suggestions,
    )

    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
