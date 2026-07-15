"""Persistent per-source dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import (
    SOURCE_REGISTRY,
    AssignmentRecord,
    PlatformScanResult,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEMORY_PATH = REPO_ROOT / "assignment-listing-seen.json"
LEGACY_MEMORY_PATHS = {
    "allakonsultuppdrag.se": REPO_ROOT / "allakonsultuppdrag-seen.json",
    "verama.com": REPO_ROOT / "verama-seen.json",
}


def empty_memory_payload() -> dict[str, Any]:
    return {
        "last_scan_at": None,
        "scan_date": None,
        "sources": {
            source.key: {
                "prefix": source.prefix,
                "seen_ids": [],
                "total_visible": 0,
                "total_unique_visible": 0,
            }
            for source in SOURCE_REGISTRY
        },
    }


def _source_prefix(source_key: str) -> str:
    for source in SOURCE_REGISTRY:
        if source.key == source_key:
            return source.prefix
    return ""


def _ids_from_legacy_file(path: Path) -> list[str]:
    if not path.is_file() or path.stat().st_size == 0:
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if isinstance(payload, list):
        return [str(item) for item in payload]
    if isinstance(payload, dict):
        for key in ("seen_ids", "seenIds", "ids"):
            value = payload.get(key)
            if isinstance(value, list):
                return [str(item) for item in value]
    return []


def collect_seen_ids_by_source(data: dict[str, Any]) -> dict[str, set[str]]:
    """Read bare source ids from current and legacy memory shapes."""
    seen: dict[str, set[str]] = {}

    sources = data.get("sources")
    if isinstance(sources, dict):
        for source_key, state in sources.items():
            if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
                seen[source_key] = {str(item) for item in state["seen_ids"]}

    # Older automation memory used platforms + seen_keys/platform:source_id.
    platforms = data.get("platforms")
    if isinstance(platforms, dict):
        for source_key, state in platforms.items():
            if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
                seen.setdefault(source_key, set()).update(str(item) for item in state["seen_ids"])

    if isinstance(data.get("seen_keys"), list):
        for key in data["seen_keys"]:
            if not isinstance(key, str) or ":" not in key:
                continue
            source_key, source_id = key.split(":", 1)
            if source_id:
                seen.setdefault(source_key, set()).add(source_id)

    # Legacy single-source allakonsult shape.
    if isinstance(data.get("seen_ids"), list):
        seen.setdefault("allakonsultuppdrag.se", set()).update(
            str(item) for item in data["seen_ids"]
        )

    return seen


def collect_seen_keys(data: dict[str, Any]) -> set[str]:
    return {
        f"{source_key}:{source_id}"
        for source_key, source_ids in collect_seen_ids_by_source(data).items()
        for source_id in source_ids
    }


def _load_json_memory(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size == 0:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize any supported shape to the unified sources object."""
    normalized = empty_memory_payload()
    normalized["last_scan_at"] = payload.get("last_scan_at")
    normalized["scan_date"] = payload.get("scan_date")

    seen_by_source = collect_seen_ids_by_source(payload)
    raw_sources = payload.get("sources") if isinstance(payload.get("sources"), dict) else {}
    for source in SOURCE_REGISTRY:
        raw_state = raw_sources.get(source.key, {}) if isinstance(raw_sources, dict) else {}
        seen_ids = sorted(seen_by_source.get(source.key, set()))
        normalized["sources"][source.key] = {
            "prefix": source.prefix,
            "seen_ids": seen_ids,
            "total_visible": raw_state.get("total_visible", len(seen_ids))
            if isinstance(raw_state, dict)
            else len(seen_ids),
            "total_unique_visible": raw_state.get("total_unique_visible", len(seen_ids))
            if isinstance(raw_state, dict)
            else len(seen_ids),
        }

    return normalized


def load_memory(path: Path) -> tuple[dict[str, set[str]], dict[str, Any]]:
    payload = _load_json_memory(path)

    if not payload:
        legacy_sources = {
            source_key: set(_ids_from_legacy_file(legacy_path))
            for source_key, legacy_path in LEGACY_MEMORY_PATHS.items()
        }
        legacy_sources = {key: ids for key, ids in legacy_sources.items() if ids}
        if legacy_sources:
            payload = empty_memory_payload()
            for source_key, source_ids in legacy_sources.items():
                payload["sources"][source_key] = {
                    "prefix": _source_prefix(source_key),
                    "seen_ids": sorted(source_ids),
                    "total_visible": len(source_ids),
                    "total_unique_visible": len(source_ids),
                }
        else:
            return {}, {}

    normalized = normalize_memory_payload(payload)
    return collect_seen_ids_by_source(normalized), normalized


def build_memory_payload(
    *,
    assignments: list[AssignmentRecord],
    source_results: list[PlatformScanResult],
    scan_date: date,
    previous_memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Save visible ids for successful sources while preserving failed sources."""
    now = datetime.now(UTC).isoformat()
    payload = normalize_memory_payload(previous_memory or empty_memory_payload())
    payload["last_scan_at"] = now
    payload["scan_date"] = scan_date.isoformat()

    ids_by_source: dict[str, set[str]] = {}
    for assignment in assignments:
        ids_by_source.setdefault(assignment.source_key, set()).add(assignment.source_id)

    for result in source_results:
        if result.status != "ok":
            continue
        prefix = _source_prefix(result.source_key)
        source_ids = sorted(ids_by_source.get(result.source_key, set()))
        payload["sources"][result.source_key] = {
            "prefix": prefix,
            "seen_ids": source_ids,
            "total_visible": result.count,
            "total_unique_visible": len(source_ids),
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
