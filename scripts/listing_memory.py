"""Persistent dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import AssignmentRecord, PlatformScanResult, SOURCE_REGISTRY

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEMORY_PATH = REPO_ROOT / "assignment-listing-seen.json"


def collect_seen_keys(data: dict[str, Any]) -> set[str]:
    """Read seen dedupe keys from current or legacy memory shapes."""
    seen_keys: set[str] = set()
    sources = data.get("sources")
    if isinstance(sources, dict):
        for source_key, state in sources.items():
            if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
                for source_id in state["seen_ids"]:
                    seen_keys.add(f"{source_key}:{source_id}")

    if isinstance(data.get("seen_keys"), list):
        seen_keys.update(str(item) for item in data["seen_keys"])

    platforms = data.get("platforms")
    if isinstance(platforms, dict):
        for platform_id, state in platforms.items():
            if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
                for source_id in state["seen_ids"]:
                    seen_keys.add(f"{platform_id}:{source_id}")

    legacy_seen = data.get("seen_ids")
    if isinstance(legacy_seen, list):
        for source_id in legacy_seen:
            seen_keys.add(f"allakonsultuppdrag.se:{source_id}")

    return seen_keys


def _source_seen_ids(source_key: str, seen_keys: set[str]) -> list[str]:
    prefix = f"{source_key}:"
    return sorted(key.split(":", 1)[1] for key in seen_keys if key.startswith(prefix))


def _empty_source_state(source_key: str) -> dict[str, Any]:
    return {
        "prefix": SOURCE_REGISTRY[source_key]["prefix"],
        "seen_ids": [],
        "total_visible": 0,
        "total_unique_visible": 0,
    }


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the unified per-source memory shape, importing legacy variants."""
    seen_keys = collect_seen_keys(payload)
    raw_sources = payload.get("sources")
    raw_platforms = payload.get("platforms")
    sources: dict[str, Any] = {}
    for source_key in SOURCE_REGISTRY:
        entry = _empty_source_state(source_key)
        if isinstance(raw_sources, dict) and isinstance(raw_sources.get(source_key), dict):
            state = raw_sources[source_key]
            entry["total_visible"] = int(state.get("total_visible") or 0)
            entry["total_unique_visible"] = int(state.get("total_unique_visible") or 0)
        elif isinstance(raw_platforms, dict) and isinstance(raw_platforms.get(source_key), dict):
            state = raw_platforms[source_key]
            entry["total_visible"] = int(state.get("total_visible") or 0)
            entry["total_unique_visible"] = int(
                state.get("total_unique_visible") or state.get("total_visible") or 0
            )
        entry["seen_ids"] = _source_seen_ids(source_key, seen_keys)
        sources[source_key] = entry

    normalized: dict[str, Any] = {
        "last_scan_at": payload.get("last_scan_at"),
        "scan_date": payload.get("scan_date"),
        "sources": sources,
    }
    return normalized


def load_memory(path: Path) -> tuple[set[str], dict[str, Any]]:
    if not path.is_file() or path.stat().st_size == 0:
        return set(), {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set(), {}

    return collect_seen_keys(data), data


def build_memory_payload(
    *,
    assignments: list[AssignmentRecord],
    platform_results: list[PlatformScanResult],
    scan_date: date,
    previous_memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    previous = normalize_memory_payload(previous_memory or {})
    sources: dict[str, Any] = {}
    assignments_by_source: dict[str, list[AssignmentRecord]] = {}
    for assignment in assignments:
        assignments_by_source.setdefault(assignment.platform, []).append(assignment)
    result_by_source = {result.platform: result for result in platform_results}

    for source_key in SOURCE_REGISTRY:
        previous_state = (
            previous.get("sources", {}).get(source_key)
            if isinstance(previous.get("sources"), dict)
            else None
        ) or _empty_source_state(source_key)
        result = result_by_source.get(source_key)
        if result is None or result.status != "ok":
            sources[source_key] = previous_state
            continue
        visible_ids = sorted({item.source_id for item in assignments_by_source.get(source_key, [])})
        sources[source_key] = {
            "prefix": SOURCE_REGISTRY[source_key]["prefix"],
            "seen_ids": visible_ids,
            "total_visible": result.count,
            "total_unique_visible": len(visible_ids),
        }

    return {
        "last_scan_at": now,
        "scan_date": scan_date.isoformat(),
        "sources": sources,
    }


def memory_stats(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_memory_payload(payload)
    source_states = normalized.get("sources") or {}
    return {
        "previously_seen": len(collect_seen_keys(normalized)),
        "sources": {
            key: {
                "seen_ids": len(value.get("seen_ids") or []),
                "total_visible": value.get("total_visible", 0),
                "total_unique_visible": value.get("total_unique_visible", 0),
            }
            for key, value in source_states.items()
            if isinstance(value, dict)
        },
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
