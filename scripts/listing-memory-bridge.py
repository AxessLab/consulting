#!/usr/bin/env python3
"""Bridge assignment listing dedupe memory and Cursor automation Memories."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from listing_memory import DEFAULT_MEMORY_PATH, load_memory, write_memory_file

MEMORY_ENTRY_NAME = "assignment-listing-seen.json"


def cmd_seed(args: argparse.Namespace) -> int:
    raw = sys.stdin.read().strip()
    if not raw:
        print("No memory content on stdin; starting with empty dedupe state.", file=sys.stderr)
        return 0

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON for {MEMORY_ENTRY_NAME}: {exc}") from exc

    if not isinstance(payload, dict):
        raise SystemExit(f"{MEMORY_ENTRY_NAME} must be a JSON object.")

    write_memory_file(args.memory_path, payload)
    seen_keys, _ = load_memory(args.memory_path)
    print(
        f"Seeded {args.memory_path.name} with {len(seen_keys)} seen key(s).",
        file=sys.stderr,
    )
    return 0


def cmd_print(args: argparse.Namespace) -> int:
    if not args.memory_path.is_file() or args.memory_path.stat().st_size == 0:
        return 0
    sys.stdout.write(args.memory_path.read_text(encoding="utf-8"))
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    seen_keys, _ = load_memory(args.memory_path)
    print(json.dumps({"previously_seen": len(seen_keys), "memory_path": str(args.memory_path)}))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--memory-path",
        type=Path,
        default=DEFAULT_MEMORY_PATH,
        help="Path to assignment-listing-seen.json",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "seed",
        help=f"Write stdin JSON to {DEFAULT_MEMORY_PATH.name} before fetch",
    )
    subparsers.add_parser(
        "print",
        help=f"Print {DEFAULT_MEMORY_PATH.name} for saving to automation Memories",
    )
    subparsers.add_parser(
        "stats",
        help="Print previously_seen count as JSON",
    )

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "seed":
        return cmd_seed(args)
    if args.command == "print":
        return cmd_print(args)
    if args.command == "stats":
        return cmd_stats(args)
    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
