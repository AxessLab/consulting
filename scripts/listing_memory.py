"""Persistent dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import DEFAULT_PLATFORMS, SOURCE_PREFIXES, AssignmentRecord, PlatformScanResult

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEMORY_PATH = REPO_ROOT / "assignment-listing-seen.json"


def collect_seen_ids_by_source(data: dict[str, Any]) -> dict[str, set[str]]:
    """Read per-source seen ids from current or legacy memory shapes."""
    seen_by_source: dict[str, set[str]] = {}
    sources = data.get("sources")
    if isinstance(sources, dict):
        for source_key, state in sources.items():
            if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
                seen_by_source[source_key] = {str(item) for item in state["seen_ids"]}

    if isinstance(data.get("seen_keys"), list):
        for item in data["seen_keys"]:
            key = str(item)
            if ":" not in key:
                continue
            source_key, source_id = key.split(":", 1)
            seen_by_source.setdefault(source_key, set()).add(source_id)

    platforms = data.get("platforms")
    if isinstance(platforms, dict):
        for platform_id, state in platforms.items():
            if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
                for source_id in state["seen_ids"]:
                    seen_by_source.setdefault(platform_id, set()).add(str(source_id))

    legacy_seen = data.get("seen_ids")
    if isinstance(legacy_seen, list):
        for source_id in legacy_seen:
            seen_by_source.setdefault("allakonsultuppdrag.se", set()).add(str(source_id))

    return seen_by_source


def collect_seen_keys(data: dict[str, Any]) -> set[str]:
    """Read seen dedupe keys from current or legacy memory shapes."""
    return {
        f"{source_key}:{source_id}"
        for source_key, seen_ids in collect_seen_ids_by_source(data).items()
        for source_id in seen_ids
    }


def _empty_source_state(source_key: str) -> dict[str, Any]:
    return {
        "prefix": SOURCE_PREFIXES.get(source_key, ""),
        "seen_ids": [],
        "total_visible": 0,
        "total_unique_visible": 0,
    }


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize memory to the unified `sources.<key>.seen_ids` shape."""
    seen_by_source = collect_seen_ids_by_source(payload)
    raw_sources = payload.get("sources")
    source_keys = list(dict.fromkeys([*DEFAULT_PLATFORMS, *seen_by_source.keys()]))
    sources: dict[str, Any] = {}
    if isinstance(raw_sources, dict):
        for source_key, state in raw_sources.items():
            if not isinstance(state, dict):
                continue
            if source_key not in source_keys:
                source_keys.append(source_key)

    for source_key in source_keys:
        raw_state = raw_sources.get(source_key, {}) if isinstance(raw_sources, dict) else {}
        if not isinstance(raw_state, dict):
            raw_state = {}
        seen_ids = sorted(seen_by_source.get(source_key, set()), key=lambda value: (len(value), value))
        sources[source_key] = {
            "prefix": str(raw_state.get("prefix") or SOURCE_PREFIXES.get(source_key, "")),
            "seen_ids": seen_ids,
            "total_visible": int(raw_state.get("total_visible") or len(seen_ids)),
            "total_unique_visible": int(raw_state.get("total_unique_visible") or len(seen_ids)),
        }

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
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    previous = previous or {}
    previous_sources = previous.get("sources") if isinstance(previous.get("sources"), dict) else {}
    seen_by_source = collect_seen_ids_by_source(previous)
    sources: dict[str, Any] = {}
    ids_by_source: dict[str, set[str]] = {}
    for assignment in assignments:
        ids_by_source.setdefault(assignment.platform, set()).add(assignment.source_id)

    result_by_source = {result.platform: result for result in platform_results}
    source_keys = list(dict.fromkeys([*DEFAULT_PLATFORMS, *seen_by_source.keys(), *ids_by_source.keys()]))

    for source_key in source_keys:
        previous_state = (
            previous_sources.get(source_key, {}) if isinstance(previous_sources, dict) else {}
        )
        if not isinstance(previous_state, dict):
            previous_state = {}
        result = result_by_source.get(source_key)
        if result and result.status == "ok":
            visible_ids = sorted(ids_by_source.get(source_key, set()), key=lambda value: (len(value), value))
            sources[source_key] = {
                "prefix": SOURCE_PREFIXES.get(source_key, previous_state.get("prefix", "")),
                "seen_ids": visible_ids,
                "total_visible": result.count,
                "total_unique_visible": len(visible_ids),
            }
            continue

        # Failed or skipped sources are intentionally left at their previous state.
        if previous_state:
            sources[source_key] = {
                "prefix": previous_state.get("prefix") or SOURCE_PREFIXES.get(source_key, ""),
                "seen_ids": list(previous_state.get("seen_ids") or []),
                "total_visible": previous_state.get("total_visible", 0),
                "total_unique_visible": previous_state.get("total_unique_visible", 0),
            }
        else:
            sources[source_key] = _empty_source_state(source_key)

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
