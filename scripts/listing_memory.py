"""Persistent per-source dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import AssignmentRecord, SOURCE_REGISTRY, SourceScanResult

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEMORY_PATH = REPO_ROOT / "assignment-listing-seen.json"
LEGACY_MEMORY_PATHS = {
    "allakonsultuppdrag.se": REPO_ROOT / "allakonsultuppdrag-seen.json",
    "verama.com": REPO_ROOT / "verama-seen.json",
}


def empty_source_state(source_key: str) -> dict[str, Any]:
    return {
        "prefix": SOURCE_REGISTRY[source_key].prefix,
        "seen_ids": [],
        "total_visible": 0,
        "total_unique_visible": 0,
    }


def collect_seen_ids_by_source(data: dict[str, Any]) -> dict[str, set[str]]:
    """Read per-source seen ids from current and legacy memory shapes."""
    seen_by_source: dict[str, set[str]] = {
        source_key: set() for source_key in SOURCE_REGISTRY
    }

    sources = data.get("sources")
    if isinstance(sources, dict):
        for source_key, state in sources.items():
            if source_key not in seen_by_source:
                seen_by_source[source_key] = set()
            if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
                seen_by_source[source_key].update(str(item) for item in state["seen_ids"])

    # Previous repo shape: seen_keys = ["source_key:source_id", ...].
    if isinstance(data.get("seen_keys"), list):
        for item in data["seen_keys"]:
            source_key, sep, source_id = str(item).partition(":")
            if sep and source_id:
                seen_by_source.setdefault(source_key, set()).add(source_id)

    # Previous repo shape: platforms.<source>.seen_ids.
    platforms = data.get("platforms")
    if isinstance(platforms, dict):
        for source_key, state in platforms.items():
            if source_key not in seen_by_source:
                seen_by_source[source_key] = set()
            if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
                for source_id in state["seen_ids"]:
                    seen_by_source[source_key].add(str(source_id))

    # Original single-source allakonsultuppdrag memory shape.
    legacy_seen = data.get("seen_ids")
    if isinstance(legacy_seen, list):
        for source_id in legacy_seen:
            seen_by_source.setdefault("allakonsultuppdrag.se", set()).add(str(source_id))

    return seen_by_source


def _load_legacy_file(source_key: str) -> set[str]:
    path = LEGACY_MEMORY_PATHS.get(source_key)
    if path is None or not path.is_file() or path.stat().st_size == 0:
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    if isinstance(payload, dict) and isinstance(payload.get("seen_ids"), list):
        return {str(item) for item in payload["seen_ids"]}
    if isinstance(payload, list):
        return {str(item) for item in payload}
    return set()


def _source_state_from_payload(source_key: str, state: dict[str, Any]) -> dict[str, Any]:
    seen_ids = [str(item) for item in state.get("seen_ids", [])] if isinstance(state, dict) else []
    return {
        "prefix": SOURCE_REGISTRY[source_key].prefix,
        "seen_ids": sorted(set(seen_ids), key=lambda value: (len(value), value)),
        "total_visible": int(state.get("total_visible") or len(set(seen_ids))),
        "total_unique_visible": int(state.get("total_unique_visible") or len(set(seen_ids))),
    }


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize memory to the current unified `sources` shape."""
    seen_by_source = collect_seen_ids_by_source(payload)
    sources: dict[str, Any] = {}
    raw_sources = payload.get("sources") if isinstance(payload.get("sources"), dict) else {}

    for source_key in SOURCE_REGISTRY:
        raw_state = raw_sources.get(source_key, {}) if isinstance(raw_sources, dict) else {}
        if not isinstance(raw_state, dict):
            raw_state = {}
        state = _source_state_from_payload(source_key, raw_state)
        if seen_by_source.get(source_key):
            state["seen_ids"] = sorted(
                seen_by_source[source_key],
                key=lambda value: (len(value), value),
            )
            if not state.get("total_visible"):
                state["total_visible"] = len(state["seen_ids"])
            if not state.get("total_unique_visible"):
                state["total_unique_visible"] = len(state["seen_ids"])
        sources[source_key] = state

    normalized: dict[str, Any] = {
        "last_scan_at": payload.get("last_scan_at"),
        "scan_date": payload.get("scan_date"),
        "sources": sources,
    }
    return normalized


def load_memory(path: Path) -> tuple[dict[str, set[str]], dict[str, Any]]:
    if not path.is_file() or path.stat().st_size == 0:
        seen_by_source = {source_key: _load_legacy_file(source_key) for source_key in SOURCE_REGISTRY}
        return seen_by_source, {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        seen_by_source = {source_key: _load_legacy_file(source_key) for source_key in SOURCE_REGISTRY}
        return seen_by_source, {}

    seen_by_source = collect_seen_ids_by_source(data)
    for source_key in SOURCE_REGISTRY:
        if not seen_by_source.get(source_key):
            seen_by_source[source_key] = _load_legacy_file(source_key)
    return seen_by_source, data


def build_memory_payload(
    *,
    assignments: list[AssignmentRecord],
    source_results: list[SourceScanResult],
    scan_date: date,
    previous_memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    previous = normalize_memory_payload(previous_memory or {})
    previous_sources = previous.get("sources", {})
    assignments_by_source: dict[str, dict[str, AssignmentRecord]] = {}
    for assignment in assignments:
        assignments_by_source.setdefault(assignment.source_key, {})[
            assignment.source_id
        ] = assignment

    successful_sources = {result.source_key for result in source_results if result.status == "ok"}
    sources: dict[str, Any] = {}
    for source_key in SOURCE_REGISTRY:
        if source_key in successful_sources:
            unique_ids = sorted(
                assignments_by_source.get(source_key, {}),
                key=lambda value: (len(value), value),
            )
            sources[source_key] = {
                "prefix": SOURCE_REGISTRY[source_key].prefix,
                "seen_ids": unique_ids,
                "total_visible": next(
                    (result.count for result in source_results if result.source_key == source_key),
                    len(unique_ids),
                ),
                "total_unique_visible": len(unique_ids),
            }
        else:
            previous_state = previous_sources.get(source_key)
            sources[source_key] = (
                _source_state_from_payload(source_key, previous_state)
                if isinstance(previous_state, dict)
                else empty_source_state(source_key)
            )

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


def total_seen_ids(seen_by_source: dict[str, set[str]]) -> int:
    return sum(len(ids) for ids in seen_by_source.values())
