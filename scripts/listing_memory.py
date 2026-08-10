"""Persistent dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import (
    SOURCE_PREFIXES,
    SOURCE_REGISTRY,
    AssignmentRecord,
    PlatformScanResult,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEMORY_PATH = REPO_ROOT / "assignment-listing-seen.json"


def empty_source_entry(source_key: str) -> dict[str, Any]:
    return {
        "prefix": SOURCE_PREFIXES[source_key],
        "seen_ids": [],
        "total_visible": 0,
        "total_unique_visible": 0,
    }


def collect_seen_ids_by_source(data: dict[str, Any]) -> dict[str, set[str]]:
    """Read bare source ids keyed by source from current and legacy memory shapes."""
    seen_by_source: dict[str, set[str]] = {
        source["source_key"]: set() for source in SOURCE_REGISTRY
    }

    sources = data.get("sources")
    if isinstance(sources, dict):
        for source_key, state in sources.items():
            if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
                seen_by_source.setdefault(source_key, set()).update(
                    str(source_id) for source_id in state["seen_ids"]
                )

    platforms = data.get("platforms")
    if isinstance(platforms, dict):
        for source_key, state in platforms.items():
            if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
                seen_by_source.setdefault(source_key, set()).update(
                    str(source_id) for source_id in state["seen_ids"]
                )

    if isinstance(data.get("seen_keys"), list):
        for key in data["seen_keys"]:
            source_key, separator, source_id = str(key).partition(":")
            if separator:
                seen_by_source.setdefault(source_key, set()).add(source_id)

    legacy_seen = data.get("seen_ids")
    if isinstance(legacy_seen, list):
        seen_by_source.setdefault("allakonsultuppdrag.se", set()).update(
            str(source_id) for source_id in legacy_seen
        )

    return seen_by_source


def collect_seen_keys(data: dict[str, Any]) -> set[str]:
    """Read seen dedupe keys from current or legacy memory shapes."""
    seen_keys: set[str] = set()
    for source_key, seen_ids in collect_seen_ids_by_source(data).items():
        for source_id in seen_ids:
            seen_keys.add(f"{source_key}:{source_id}")

    return seen_keys


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize memory to the unified per-source shape used by cloud runs."""
    seen_by_source = collect_seen_ids_by_source(payload)
    sources: dict[str, Any] = {}
    raw_sources = payload.get("sources") if isinstance(payload.get("sources"), dict) else {}
    raw_platforms = payload.get("platforms") if isinstance(payload.get("platforms"), dict) else {}

    for source in SOURCE_REGISTRY:
        source_key = source["source_key"]
        state = {}
        if isinstance(raw_sources, dict) and isinstance(raw_sources.get(source_key), dict):
            state = raw_sources[source_key]
        elif isinstance(raw_platforms, dict) and isinstance(raw_platforms.get(source_key), dict):
            state = raw_platforms[source_key]

        seen_ids = sorted(seen_by_source.get(source_key, set()), key=lambda value: (len(value), value))
        sources[source_key] = {
            "prefix": source["prefix"],
            "seen_ids": seen_ids,
            "total_visible": int(state.get("total_visible") or len(seen_ids)),
            "total_unique_visible": int(state.get("total_unique_visible") or len(seen_ids)),
        }

    normalized: dict[str, Any] = {
        "last_scan_at": payload.get("last_scan_at"),
        "scan_date": payload.get("scan_date"),
        "sources": sources,
    }
    return normalized


def load_memory(path: Path) -> tuple[set[str], dict[str, Any], dict[str, set[str]]]:
    if not path.is_file() or path.stat().st_size == 0:
        return set(), {}, {source["source_key"]: set() for source in SOURCE_REGISTRY}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set(), {}, {source["source_key"]: set() for source in SOURCE_REGISTRY}

    return collect_seen_keys(data), data, collect_seen_ids_by_source(data)


def build_memory_payload(
    *,
    assignments: list[AssignmentRecord],
    platform_results: list[PlatformScanResult],
    scan_date: date,
    existing_memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    payload = normalize_memory_payload(existing_memory or {})
    payload["last_scan_at"] = now
    payload["scan_date"] = scan_date.isoformat()

    by_source: dict[str, set[str]] = {}
    for assignment in assignments:
        by_source.setdefault(assignment.source_key, set()).add(assignment.source_id)

    sources = payload.setdefault("sources", {})
    for result in platform_results:
        if result.status != "ok":
            continue
        if result.platform not in SOURCE_PREFIXES:
            continue
        seen_ids = sorted(by_source.get(result.platform, set()), key=lambda value: (len(value), value))
        sources[result.platform] = {
            "prefix": SOURCE_PREFIXES[result.platform],
            "seen_ids": seen_ids,
            "total_visible": result.count,
            "total_unique_visible": len(seen_ids),
        }

    return payload


def write_memory_file(memory_path: Path, payload: dict[str, Any]) -> None:
    normalized = normalize_memory_payload(payload)
    memory_path.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def commit_memory(payload_path: Path, memory_path: Path) -> None:
    data = json.loads(payload_path.read_text(encoding="utf-8"))
    memory_update = data.get("memory_update")
    if not isinstance(memory_update, dict):
        raise ValueError("listing output is missing memory_update")
    write_memory_file(memory_path, memory_update)


def read_memory_export(memory_path: Path) -> str:
    if not memory_path.is_file() or memory_path.stat().st_size == 0:
        return ""
    return memory_path.read_text(encoding="utf-8")
