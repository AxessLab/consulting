"""Persistent per-source dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import AssignmentRecord, PlatformScanResult, SOURCE_REGISTRY

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEMORY_PATH = REPO_ROOT / "assignment-listing-seen.json"


def _empty_source_state(source_key: str) -> dict[str, Any]:
    return {
        "prefix": SOURCE_REGISTRY[source_key]["prefix"],
        "seen_ids": [],
        "total_visible": 0,
        "total_unique_visible": 0,
    }


def collect_seen_by_source(data: dict[str, Any]) -> dict[str, set[str]]:
    """Read per-source seen ids from current and legacy memory shapes."""
    seen_by_source: dict[str, set[str]] = {key: set() for key in SOURCE_REGISTRY}

    sources = data.get("sources")
    if isinstance(sources, dict):
        for source_key, state in sources.items():
            if not isinstance(state, dict) or not isinstance(state.get("seen_ids"), list):
                continue
            seen_by_source.setdefault(source_key, set()).update(
                str(item) for item in state["seen_ids"]
            )

    # Legacy shapes used either "platforms" with seen_ids or combined seen_keys.
    platforms = data.get("platforms")
    if isinstance(platforms, dict):
        for source_key, state in platforms.items():
            if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
                seen_by_source.setdefault(source_key, set()).update(
                    str(item) for item in state["seen_ids"]
                )

    if isinstance(data.get("seen_keys"), list):
        for key in data["seen_keys"]:
            source_key, separator, source_id = str(key).partition(":")
            if separator:
                seen_by_source.setdefault(source_key, set()).add(source_id)

    legacy_seen = data.get("seen_ids")
    if isinstance(legacy_seen, list):
        seen_by_source.setdefault("allakonsultuppdrag.se", set()).update(
            str(item) for item in legacy_seen
        )

    return seen_by_source


def collect_seen_keys(data: dict[str, Any]) -> set[str]:
    """Compatibility helper for callers that still use source_key:source_id keys."""
    seen_keys: set[str] = set()
    for source_key, seen_ids in collect_seen_by_source(data).items():
        seen_keys.update(f"{source_key}:{source_id}" for source_id in seen_ids)
    return seen_keys


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize persisted memory to the unified per-source shape."""
    seen_by_source = collect_seen_by_source(payload)
    raw_sources = payload.get("sources") if isinstance(payload.get("sources"), dict) else {}
    sources: dict[str, Any] = {}

    for source_key in SOURCE_REGISTRY:
        raw_state = raw_sources.get(source_key, {}) if isinstance(raw_sources, dict) else {}
        if not isinstance(raw_state, dict):
            raw_state = {}
        seen_ids = sorted(seen_by_source.get(source_key, set()), key=lambda value: (len(value), value))
        sources[source_key] = {
            "prefix": SOURCE_REGISTRY[source_key]["prefix"],
            "seen_ids": seen_ids,
            "total_visible": int(raw_state.get("total_visible") or len(seen_ids)),
            "total_unique_visible": int(raw_state.get("total_unique_visible") or len(seen_ids)),
        }

    return {
        "last_scan_at": payload.get("last_scan_at"),
        "scan_date": payload.get("scan_date"),
        "sources": sources,
    }


def load_memory(path: Path) -> tuple[set[str], dict[str, Any]]:
    if not path.is_file() or path.stat().st_size == 0:
        return set(), {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set(), {}

    normalized = normalize_memory_payload(data)
    return collect_seen_keys(normalized), normalized


def load_seen_by_source(path: Path) -> tuple[dict[str, set[str]], dict[str, Any]]:
    if not path.is_file() or path.stat().st_size == 0:
        return {key: set() for key in SOURCE_REGISTRY}, {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {key: set() for key in SOURCE_REGISTRY}, {}

    normalized = normalize_memory_payload(data)
    return collect_seen_by_source(normalized), normalized


def build_memory_payload(
    *,
    assignments: list[AssignmentRecord],
    platform_results: list[PlatformScanResult],
    scan_date: date,
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    successful_sources = {
        result.platform for result in platform_results if result.status == "ok"
    }
    ids_by_source: dict[str, set[str]] = {key: set() for key in SOURCE_REGISTRY}
    for assignment in assignments:
        if assignment.platform in successful_sources:
            ids_by_source.setdefault(assignment.platform, set()).add(assignment.source_id)

    result_by_source = {result.platform: result for result in platform_results}
    sources: dict[str, Any] = {}
    for source_key in SOURCE_REGISTRY:
        result = result_by_source.get(source_key)
        seen_ids = sorted(ids_by_source.get(source_key, set()), key=lambda value: (len(value), value))
        sources[source_key] = {
            "prefix": SOURCE_REGISTRY[source_key]["prefix"],
            "seen_ids": seen_ids,
            "total_visible": result.count if result and result.status == "ok" else 0,
            "total_unique_visible": len(seen_ids) if result and result.status == "ok" else 0,
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
