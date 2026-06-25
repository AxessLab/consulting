#!/usr/bin/env python3
"""Raw multi-platform assignment fetch (no filtering). Prefer list-assignments.py."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from assignment_platforms import DEFAULT_PLATFORMS, scan_platforms


def build_slack_debug_summary(platform_results: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for result in platform_results:
        label = result["platform"]
        if result["status"] == "ok":
            parts.append(f"{label} ({result['count']})")
        elif result["status"] == "skipped":
            parts.append(f"{label} (skipped)")
        else:
            parts.append(f"{label} (error)")
    return "Scanned platforms: " + ", ".join(parts)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--platform",
        action="append",
        dest="platforms",
        choices=DEFAULT_PLATFORMS,
        help="Platform to scan (default: all registered platforms)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Limit allakonsultuppdrag.se pagination (testing)",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run Verama browser login with a visible window",
    )
    parser.add_argument(
        "--debug-summary",
        action="store_true",
        help="Print a Slack-ready platform summary line to stderr",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    import os

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    args = parse_args(argv)
    platform_ids = args.platforms or DEFAULT_PLATFORMS

    assignments, results = scan_platforms(
        platform_ids,
        max_pages=args.max_pages,
        headless=not args.headed,
    )

    payload = {
        "scannedAt": datetime.now(UTC).isoformat(),
        "platforms": [asdict(result) for result in results],
        "assignments": [record.to_dict() for record in assignments],
    }

    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")

    if args.debug_summary:
        print(build_slack_debug_summary(payload["platforms"]), file=sys.stderr)

    failed = [p for p in payload["platforms"] if p["status"] == "error"]
    return 1 if failed and not payload["assignments"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
