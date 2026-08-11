"""Persistent per-source dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import (
    DEFAULT_SOURCES,
    SOURCE_PREFIXES,
    AssignmentRecord,
    PlatformScanResult,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEMORY_PATH = REPO_ROOT / "assignment-listing-seen.json"


def empty_source_state(source_key: str) -> dict[str, Any]:
    return {
        "prefix": SOURCE_PREFIXES[source_key],
        "seen_ids": [],
        "total_visible": 0,
        "total_unique_visible": 0,
    }


def _source_id_from_dedupe_key(value: str) -> tuple[str, str] | None:
    if ":" not in value:
        return None
    source_key, source_id = value.split(":", 1)
    if not source_key or not source_id:
        return None
    return source_key, source_id


def _seen_ids_from_state(state: Any) -> list[str]:
    if not isinstance(state, dict) or not isinstance(state.get("seen_ids"), list):
        return []
    return sorted({str(item) for item in state["seen_ids"]})


def collect_seen_ids_by_source(data: dict[str, Any]) -> dict[str, set[str]]:
    """Read seen ids from the current memory shape and older one-off formats."""
    seen: dict[str, set[str]] = {source_key: set() for source_key in DEFAULT_SOURCES}

    sources = data.get("sources")
    if isinstance(sources, dict):
        for source_key, state in sources.items():
            if source_key not in seen:
                seen[source_key] = set()
            seen[source_key].update(_seen_ids_from_state(state))

    # Legacy unified memory used platform:source_id strings.
    if isinstance(data.get("seen_keys"), list):
        for item in data["seen_keys"]:
            parsed = _source_id_from_dedupe_key(str(item))
            if parsed is None:
                continue
            source_key, source_id = parsed
            seen.setdefault(source_key, set()).add(source_id)

    # Legacy intermediate shape used "platforms" instead of "sources".
    platforms = data.get("platforms")
    if isinstance(platforms, dict):
        for source_key, state in platforms.items():
            seen.setdefault(source_key, set()).update(_seen_ids_from_state(state))

    # Old allakonsult-only memory files stored bare ids at top level.
    if isinstance(data.get("seen_ids"), list):
        seen.setdefault("allakonsultuppdrag.se", set()).update(
            str(item) for item in data["seen_ids"]
        )

    return seen


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the supported unified memory shape with one entry per source."""
    seen_by_source = collect_seen_ids_by_source(payload)
    raw_sources = payload.get("sources") if isinstance(payload.get("sources"), dict) else {}
    sources: dict[str, Any] = {}

    for source_key in DEFAULT_SOURCES:
        raw_state = raw_sources.get(source_key) if isinstance(raw_sources, dict) else None
        entry = empty_source_state(source_key)
        entry["seen_ids"] = sorted(seen_by_source.get(source_key, set()))
        if isinstance(raw_state, dict):
            entry["total_visible"] = int(raw_state.get("total_visible") or len(entry["seen_ids"]))
            entry["total_unique_visible"] = int(
                raw_state.get("total_unique_visible") or len(entry["seen_ids"])
            )
        else:
            entry["total_visible"] = len(entry["seen_ids"])
            entry["total_unique_visible"] = len(entry["seen_ids"])
        sources[source_key] = entry

    return {
        "last_scan_at": payload.get("last_scan_at"),
        "scan_date": payload.get("scan_date"),
        "sources": sources,
    }


def load_memory(path: Path) -> tuple[dict[str, set[str]], dict[str, Any]]:
    if not path.is_file() or path.stat().st_size == 0:
        empty = normalize_memory_payload({})
        return collect_seen_ids_by_source(empty), empty
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        empty = normalize_memory_payload({})
        return collect_seen_ids_by_source(empty), empty

    normalized = normalize_memory_payload(data)
    return collect_seen_ids_by_source(normalized), normalized


def build_memory_payload(
    *,
    assignments: list[AssignmentRecord],
    source_results: list[PlatformScanResult],
    scan_date: date,
    previous_memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Update successful sources only; preserve failed/skipped source memory."""
    previous = normalize_memory_payload(previous_memory or {})
    sources = {
        source_key: dict(state)
        for source_key, state in previous.get("sources", {}).items()
        if source_key in SOURCE_PREFIXES
    }
    for source_key in DEFAULT_SOURCES:
        sources.setdefault(source_key, empty_source_state(source_key))

    ids_by_source: dict[str, set[str]] = {}
    for assignment in assignments:
        ids_by_source.setdefault(assignment.source_key, set()).add(assignment.source_id)

    for result in source_results:
        source_key = result.source_key
        sources.setdefault(source_key, empty_source_state(source_key))
        if result.status != "ok":
            continue
        seen_ids = sorted(ids_by_source.get(source_key, set()))
        sources[source_key] = {
            "prefix": SOURCE_PREFIXES[source_key],
            "seen_ids": seen_ids,
            "total_visible": result.count,
            "total_unique_visible": len(seen_ids),
        }

    return {
        "last_scan_at": datetime.now(UTC).isoformat(),
        "scan_date": scan_date.isoformat(),
        "sources": {source_key: sources[source_key] for source_key in DEFAULT_SOURCES},
    }


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
