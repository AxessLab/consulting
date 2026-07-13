"""Persistent dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import AssignmentRecord, PlatformScanResult, SOURCE_REGISTRY

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEMORY_PATH = REPO_ROOT / "assignment-listing-seen.json"


def _default_source_state(source_key: str) -> dict[str, Any]:
    return {
        "prefix": SOURCE_REGISTRY[source_key]["prefix"],
        "seen_ids": [],
        "total_visible": 0,
        "total_unique_visible": 0,
    }


def _source_ids_from_seen_keys(items: list[Any]) -> dict[str, set[str]]:
    seen_by_source: dict[str, set[str]] = {key: set() for key in SOURCE_REGISTRY}
    for item in items:
        value = str(item)
        if ":" not in value:
            continue
        source_key, source_id = value.split(":", 1)
        if source_key in SOURCE_REGISTRY and source_id:
            seen_by_source.setdefault(source_key, set()).add(source_id)
    return seen_by_source


def collect_seen_ids_by_source(data: dict[str, Any]) -> dict[str, set[str]]:
    """Read bare seen ids from current and legacy memory shapes."""
    seen_by_source: dict[str, set[str]] = {key: set() for key in SOURCE_REGISTRY}

    sources = data.get("sources")
    if isinstance(sources, dict):
        for source_key, state in sources.items():
            if source_key not in SOURCE_REGISTRY or not isinstance(state, dict):
                continue
            seen_ids = state.get("seen_ids")
            if isinstance(seen_ids, list):
                seen_by_source[source_key].update(str(item) for item in seen_ids)

    # Legacy shape used "platforms" with bare ids nested per platform.
    platforms = data.get("platforms")
    if isinstance(platforms, dict):
        for source_key, state in platforms.items():
            if source_key not in SOURCE_REGISTRY or not isinstance(state, dict):
                continue
            seen_ids = state.get("seen_ids")
            if isinstance(seen_ids, list):
                seen_by_source[source_key].update(str(item) for item in seen_ids)

    # Legacy multi-platform shape used fully-qualified "platform:id" keys.
    if isinstance(data.get("seen_keys"), list):
        for source_key, ids in _source_ids_from_seen_keys(data["seen_keys"]).items():
            seen_by_source.setdefault(source_key, set()).update(ids)

    # Legacy single-source allakonsultuppdrag memory.
    if isinstance(data.get("seen_ids"), list):
        seen_by_source.setdefault("allakonsultuppdrag.se", set()).update(
            str(item) for item in data["seen_ids"]
        )

    return seen_by_source


def collect_seen_keys(data: dict[str, Any]) -> set[str]:
    """Compatibility helper for older callers: return "source:id" keys."""
    seen_keys: set[str] = set()
    for source_key, seen_ids in collect_seen_ids_by_source(data).items():
        seen_keys.update(f"{source_key}:{source_id}" for source_id in seen_ids)
    return seen_keys


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize memory to the unified per-source schema."""
    seen_by_source = collect_seen_ids_by_source(payload)
    normalized_sources: dict[str, Any] = {}
    raw_sources = payload.get("sources") if isinstance(payload.get("sources"), dict) else {}

    for source_key in SOURCE_REGISTRY:
        raw_state = raw_sources.get(source_key, {}) if isinstance(raw_sources, dict) else {}
        if not isinstance(raw_state, dict):
            raw_state = {}
        seen_ids = sorted(seen_by_source.get(source_key, set()))
        normalized_sources[source_key] = {
            "prefix": SOURCE_REGISTRY[source_key]["prefix"],
            "seen_ids": seen_ids,
            "total_visible": int(raw_state.get("total_visible") or len(seen_ids)),
            "total_unique_visible": int(raw_state.get("total_unique_visible") or len(seen_ids)),
        }

    return {
        "last_scan_at": payload.get("last_scan_at"),
        "scan_date": payload.get("scan_date"),
        "sources": normalized_sources,
    }


def load_memory(path: Path) -> tuple[dict[str, set[str]], dict[str, Any]]:
    if not path.is_file() or path.stat().st_size == 0:
        return {key: set() for key in SOURCE_REGISTRY}, {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {key: set() for key in SOURCE_REGISTRY}, {}

    normalized = normalize_memory_payload(data)
    return collect_seen_ids_by_source(normalized), normalized


def build_memory_payload(
    *,
    assignments: list[AssignmentRecord],
    platform_results: list[PlatformScanResult],
    scan_date: date,
    previous_memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    memory = normalize_memory_payload(previous_memory or {})
    sources: dict[str, Any] = {
        source_key: dict(state) for source_key, state in memory.get("sources", {}).items()
    }
    for source_key in SOURCE_REGISTRY:
        sources.setdefault(source_key, _default_source_state(source_key))

    assignments_by_source: dict[str, list[AssignmentRecord]] = {}
    for assignment in assignments:
        assignments_by_source.setdefault(assignment.source_key, []).append(assignment)

    for result in platform_results:
        if result.status != "ok":
            continue
        source_assignments = assignments_by_source.get(result.source_key, [])
        unique_ids = sorted({assignment.source_id for assignment in source_assignments})
        sources[result.source_key] = {
            "prefix": SOURCE_REGISTRY[result.source_key]["prefix"],
            "seen_ids": unique_ids,
            "total_visible": result.count,
            "total_unique_visible": len(unique_ids),
        }

    return {
        "last_scan_at": now,
        "scan_date": scan_date.isoformat(),
        "sources": sources,
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
