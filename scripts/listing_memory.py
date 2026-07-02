"""Persistent per-source dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import (
    ALLAKONSULT_KEY,
    SOURCE_REGISTRY,
    AssignmentRecord,
    PlatformScanResult,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEMORY_PATH = REPO_ROOT / "assignment-listing-seen.json"


def _empty_sources() -> dict[str, dict[str, Any]]:
    return {
        source.key: {
            "prefix": source.prefix,
            "seen_ids": [],
            "total_visible": 0,
            "total_unique_visible": 0,
        }
        for source in SOURCE_REGISTRY
        if source.active
    }


def _coerce_seen_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({str(item) for item in value if str(item)})


def _legacy_sources_from_payload(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sources = _empty_sources()

    raw_sources = payload.get("sources")
    if isinstance(raw_sources, dict):
        for source in SOURCE_REGISTRY:
            state = raw_sources.get(source.key)
            if not isinstance(state, dict):
                continue
            sources[source.key] = {
                "prefix": str(state.get("prefix") or source.prefix),
                "seen_ids": _coerce_seen_ids(state.get("seen_ids")),
                "total_visible": int(state.get("total_visible") or 0),
                "total_unique_visible": int(state.get("total_unique_visible") or 0),
            }
        return sources

    raw_platforms = payload.get("platforms")
    if isinstance(raw_platforms, dict):
        for source in SOURCE_REGISTRY:
            state = raw_platforms.get(source.key)
            if not isinstance(state, dict):
                continue
            sources[source.key]["seen_ids"] = _coerce_seen_ids(state.get("seen_ids"))
            sources[source.key]["total_visible"] = int(state.get("total_visible") or 0)
            sources[source.key]["total_unique_visible"] = len(sources[source.key]["seen_ids"])

    # Older multi-source memory stored "source:id" strings in one seen_keys array.
    seen_keys = payload.get("seen_keys")
    if isinstance(seen_keys, list):
        by_source: dict[str, set[str]] = {source.key: set() for source in SOURCE_REGISTRY}
        for item in seen_keys:
            key = str(item)
            if ":" not in key:
                continue
            source_key, source_id = key.split(":", 1)
            if source_key in by_source and source_id:
                by_source[source_key].add(source_id)
        for source_key, ids in by_source.items():
            if ids:
                sources[source_key]["seen_ids"] = sorted(ids)
                sources[source_key]["total_unique_visible"] = len(ids)

    # Legacy allakonsult-only memory stored bare numeric ids at top level.
    legacy_seen = payload.get("seen_ids")
    if isinstance(legacy_seen, list):
        ids = _coerce_seen_ids(legacy_seen)
        sources[ALLAKONSULT_KEY]["seen_ids"] = ids
        sources[ALLAKONSULT_KEY]["total_unique_visible"] = len(ids)
        sources[ALLAKONSULT_KEY]["total_visible"] = len(ids)

    return sources


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size == 0:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def normalize_memory_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = payload or {}
    return {
        "last_scan_at": payload.get("last_scan_at"),
        "scan_date": payload.get("scan_date"),
        "sources": _legacy_sources_from_payload(payload),
    }


def load_memory(path: Path) -> tuple[dict[str, set[str]], dict[str, Any]]:
    data = normalize_memory_payload(_read_json(path))

    if not any(state["seen_ids"] for state in data["sources"].values()):
        legacy_path = REPO_ROOT / "allakonsultuppdrag-seen.json"
        legacy_payload = _read_json(legacy_path)
        if legacy_payload:
            data = normalize_memory_payload(legacy_payload)

    seen_by_source = {
        source_key: set(state.get("seen_ids") or [])
        for source_key, state in data.get("sources", {}).items()
        if isinstance(state, dict)
    }
    return seen_by_source, data


def build_memory_payload(
    *,
    assignments: list[AssignmentRecord],
    platform_results: list[PlatformScanResult],
    scan_date: date,
    previous_memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build next memory, updating only successfully scanned sources."""

    normalized = normalize_memory_payload(previous_memory)
    sources = normalized["sources"]
    by_source: dict[str, set[str]] = {source.key: set() for source in SOURCE_REGISTRY}
    for assignment in assignments:
        by_source.setdefault(assignment.source_key, set()).add(assignment.source_id)

    for result in platform_results:
        if result.status != "ok":
            continue
        config = next((source for source in SOURCE_REGISTRY if source.key == result.source_key), None)
        if config is None:
            continue
        seen_ids = sorted(by_source.get(result.source_key, set()))
        sources[result.source_key] = {
            "prefix": config.prefix,
            "seen_ids": seen_ids,
            "total_visible": result.count,
            "total_unique_visible": len(seen_ids),
        }

    return {
        "last_scan_at": datetime.now(UTC).isoformat(),
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
