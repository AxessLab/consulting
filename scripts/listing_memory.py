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
        "prefix": SOURCE_REGISTRY[source_key].prefix,
        "seen_ids": [],
        "total_visible": 0,
        "total_unique_visible": 0,
    }


def _normalize_source_state(source_key: str, state: Any) -> dict[str, Any]:
    normalized = _empty_source_state(source_key)
    if not isinstance(state, dict):
        return normalized

    seen_ids = state.get("seen_ids")
    if isinstance(seen_ids, list):
        normalized["seen_ids"] = sorted({str(item) for item in seen_ids})

    for field in ("total_visible", "total_unique_visible"):
        value = state.get(field)
        if isinstance(value, int):
            normalized[field] = value

    prefix = state.get("prefix")
    if isinstance(prefix, str) and prefix:
        normalized["prefix"] = prefix
    return normalized


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the unified `sources` memory shape, migrating legacy payloads."""
    sources: dict[str, dict[str, Any]] = {
        source_key: _empty_source_state(source_key) for source_key in SOURCE_REGISTRY
    }

    raw_sources = payload.get("sources")
    if isinstance(raw_sources, dict):
        for source_key in SOURCE_REGISTRY:
            sources[source_key] = _normalize_source_state(
                source_key,
                raw_sources.get(source_key),
            )
    else:
        raw_platforms = payload.get("platforms")
        if isinstance(raw_platforms, dict):
            for source_key in SOURCE_REGISTRY:
                sources[source_key] = _normalize_source_state(
                    source_key,
                    raw_platforms.get(source_key),
                )

        seen_keys = payload.get("seen_keys")
        if isinstance(seen_keys, list):
            for key in seen_keys:
                if not isinstance(key, str) or ":" not in key:
                    continue
                source_key, source_id = key.split(":", 1)
                if source_key in sources:
                    sources[source_key]["seen_ids"].append(source_id)

        legacy_seen = payload.get("seen_ids")
        if isinstance(legacy_seen, list):
            sources["allakonsultuppdrag.se"]["seen_ids"].extend(
                str(source_id) for source_id in legacy_seen
            )

    for source_key, state in sources.items():
        state["prefix"] = SOURCE_REGISTRY[source_key].prefix
        state["seen_ids"] = sorted({str(item) for item in state.get("seen_ids", [])})
        if not isinstance(state.get("total_unique_visible"), int):
            state["total_unique_visible"] = len(state["seen_ids"])
        if not isinstance(state.get("total_visible"), int):
            state["total_visible"] = state["total_unique_visible"]

    return {
        "last_scan_at": payload.get("last_scan_at"),
        "scan_date": payload.get("scan_date"),
        "sources": sources,
    }


def source_seen_ids(memory: dict[str, Any], source_key: str) -> set[str]:
    state = memory.get("sources", {}).get(source_key, {})
    seen_ids = state.get("seen_ids")
    if not isinstance(seen_ids, list):
        return set()
    return {str(item) for item in seen_ids}


def seen_ids_by_source(memory: dict[str, Any]) -> dict[str, set[str]]:
    return {source_key: source_seen_ids(memory, source_key) for source_key in SOURCE_REGISTRY}


def collect_seen_keys(data: dict[str, Any]) -> set[str]:
    memory = normalize_memory_payload(data)
    return {
        f"{source_key}:{source_id}"
        for source_key, ids in seen_ids_by_source(memory).items()
        for source_id in ids
    }


def load_source_memory(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size == 0:
        return normalize_memory_payload({})
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return normalize_memory_payload({})
    if not isinstance(data, dict):
        return normalize_memory_payload({})
    return normalize_memory_payload(data)


def load_memory(path: Path) -> tuple[set[str], dict[str, Any]]:
    memory = load_source_memory(path)
    return collect_seen_keys(memory), memory


def source_is_new(memory: dict[str, Any], assignment: AssignmentRecord) -> bool:
    return assignment.source_id not in source_seen_ids(memory, assignment.source_key)


def build_memory_payload(
    *,
    assignments: list[AssignmentRecord],
    platform_results: list[PlatformScanResult],
    scan_date: date,
    previous_memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    previous = normalize_memory_payload(previous_memory or {})
    sources = {
        source_key: dict(state)
        for source_key, state in previous.get("sources", {}).items()
        if source_key in SOURCE_REGISTRY
    }
    for source_key in SOURCE_REGISTRY:
        sources.setdefault(source_key, _empty_source_state(source_key))

    assignments_by_source: dict[str, list[AssignmentRecord]] = {}
    for assignment in assignments:
        assignments_by_source.setdefault(assignment.source_key, []).append(assignment)

    for result in platform_results:
        if result.status != "ok":
            continue
        source_assignments = assignments_by_source.get(result.source_key, [])
        unique_visible = sorted({assignment.source_id for assignment in source_assignments})
        sources[result.source_key] = {
            "prefix": SOURCE_REGISTRY[result.source_key].prefix,
            "seen_ids": unique_visible,
            "total_visible": result.count,
            "total_unique_visible": len(unique_visible),
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
