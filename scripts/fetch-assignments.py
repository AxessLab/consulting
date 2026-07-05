#!/usr/bin/env python3
"""Fetch assignments from all sources, apply dedupe, emit candidates for curation."""

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
from assignment_platforms import DEFAULT_SOURCES, AssignmentRecord, scan_sources
from listing_memory import DEFAULT_MEMORY_PATH, build_memory_payload, load_memory


def build_source_summary(source_results: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for result in source_results:
        label = result["source_key"]
        if result["status"] == "ok":
            parts.append(f"{label} ({result['count']})")
        elif result["status"] == "skipped":
            parts.append(f"{label} (skipped)")
        else:
            parts.append(f"{label} (error)")
    return "Scanned sources: " + ", ".join(parts)


def prepare_candidates(
    *,
    memory_path: Path,
    source_keys: list[str],
    scan_date: date,
    max_pages: int | None = None,
    headless: bool = True,
    with_suggestions: bool = True,
) -> dict[str, Any]:
    seen_by_source, memory_payload = load_memory(memory_path)

    raw_assignments, source_results = scan_sources(
        source_keys,
        seen_ids_by_source=seen_by_source,
        scan_date=scan_date,
        max_pages=max_pages,
        headless=headless,
    )
    deduped_assignments = cross_platform_dedupe(raw_assignments)
    new_assignments = [
        assignment
        for assignment in deduped_assignments
        if assignment.source_id not in seen_by_source.get(assignment.source_key, set())
    ]
    new_ids_by_source = {
        source_key: sorted(
            {
                assignment.source_id
                for assignment in raw_assignments
                if assignment.source_key == source_key
                and assignment.source_id not in seen_by_source.get(source_key, set())
            }
        )
        for source_key in source_keys
    }

    profiles = load_consultant_profiles()
    suggestions: list[dict[str, Any]] = []
    expired: list[dict[str, Any]] = []
    if with_suggestions:
        active_suggestions, expired_suggestions = suggest_assignments(
            new_assignments,
            scan_date=scan_date,
            profiles=profiles,
        )
        suggestions = [suggestion_to_dict(item) for item in active_suggestions]
        expired = [suggestion_to_dict(item) for item in expired_suggestions]

    source_payload = [
        {
            "source_key": result.source_key,
            "status": result.status,
            "count": result.count,
            "message": result.message,
        }
        for result in source_results
    ]

    memory_update = build_memory_payload(
        assignments=raw_assignments,
        source_results=source_results,
        previous_memory=memory_payload,
        scan_date=scan_date,
    )

    suggested_report = [
        item for item in suggestions if item.get("suggested_section") is not None
    ]

    return {
        "source": "assignment-fetch",
        "scan_date": scan_date.isoformat(),
        "memory_path": str(memory_path),
        "sources": [result.source_key for result in source_results],
        "source_results": source_payload,
        "platforms": [result.source_key for result in source_results],
        "platform_results": [
            {
                "platform": result["source_key"],
                "status": result["status"],
                "count": result["count"],
                "message": result["message"],
            }
            for result in source_payload
        ],
        "source_summary": build_source_summary(source_payload),
        "platform_summary": build_source_summary(source_payload),
        "consultants": export_consultant_summaries(profiles),
        "stats": {
            "total_visible": len(raw_assignments),
            "total_unique_visible": len(deduped_assignments),
            "previously_seen": sum(len(ids) for ids in seen_by_source.values()),
            "previously_seen_by_source": {
                source_key: len(ids) for source_key, ids in seen_by_source.items()
            },
            "new_ids": len(new_assignments),
            "new_ids_by_source": {
                source_key: len(ids) for source_key, ids in new_ids_by_source.items()
            },
            "expired_new_ids": len(expired),
            "script_suggestions": len(suggested_report),
            "active_consultants": len(profiles),
        },
        "assignments": [record.to_dict() for record in deduped_assignments],
        "visible_assignments": [record.to_dict() for record in raw_assignments],
        "new_dedupe_keys": [assignment.dedupe_key for assignment in new_assignments],
        "new_source_ids_by_source": new_ids_by_source,
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
        "--source",
        action="append",
        dest="sources",
        choices=DEFAULT_SOURCES,
        help="Source to scan (default: all registered active sources)",
    )
    parser.add_argument(
        "--platform",
        action="append",
        dest="platforms",
        choices=DEFAULT_SOURCES,
        help=argparse.SUPPRESS,
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
    source_keys = args.sources or args.platforms or DEFAULT_SOURCES

    payload = prepare_candidates(
        memory_path=args.memory_path,
        source_keys=source_keys,
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
