"""Persistent dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import SOURCE_PREFIXES, AssignmentRecord, PlatformScanResult

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEMORY_PATH = REPO_ROOT / "assignment-listing-seen.json"


def _split_seen_key(value: str) -> tuple[str, str] | None:
    if ":" not in value:
        return None
    source_key, source_id = value.split(":", 1)
    if not source_key or not source_id:
        return None
    return source_key, source_id


def collect_source_seen(data: dict[str, Any]) -> dict[str, set[str]]:
    """Read per-source ids from the current memory shape and legacy shapes."""
    source_seen: dict[str, set[str]] = {}

    sources = data.get("sources")
    if isinstance(sources, dict):
        for source_key, state in sources.items():
            if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
                source_seen.setdefault(str(source_key), set()).update(
                    str(item) for item in state["seen_ids"]
                )

    seen_keys = data.get("seen_keys")
    if isinstance(seen_keys, list):
        for item in seen_keys:
            parsed = _split_seen_key(str(item))
            if parsed:
                source_key, source_id = parsed
                source_seen.setdefault(source_key, set()).add(source_id)

    platforms = data.get("platforms")
    if isinstance(platforms, dict):
        for source_key, state in platforms.items():
            if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
                source_seen.setdefault(str(source_key), set()).update(
                    str(source_id) for source_id in state["seen_ids"]
                )

    legacy_seen = data.get("seen_ids")
    if isinstance(legacy_seen, list):
        source_seen.setdefault("allakonsultuppdrag.se", set()).update(
            str(source_id) for source_id in legacy_seen
        )

    return source_seen


def collect_seen_keys(data: dict[str, Any]) -> set[str]:
    """Read seen dedupe keys from current or legacy memory shapes."""
    return {
        f"{source_key}:{source_id}"
        for source_key, seen_ids in collect_source_seen(data).items()
        for source_id in seen_ids
    }


def _state_from_payload(payload: dict[str, Any], source_key: str) -> dict[str, Any]:
    for collection_name in ("sources", "platforms"):
        collection = payload.get(collection_name)
        if isinstance(collection, dict) and isinstance(collection.get(source_key), dict):
            return collection[source_key]
    return {}


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize memory to the current per-source ``seen_ids`` shape."""
    source_seen = collect_source_seen(payload)
    source_keys = list(SOURCE_PREFIXES)
    for source_key in source_seen:
        if source_key not in source_keys:
            source_keys.append(source_key)

    sources: dict[str, Any] = {}
    for source_key in source_keys:
        state = _state_from_payload(payload, source_key)
        seen_ids = sorted(source_seen.get(source_key, set()))
        sources[source_key] = {
            "prefix": str(state.get("prefix") or SOURCE_PREFIXES.get(source_key, "")),
            "seen_ids": seen_ids,
            "total_visible": int(state.get("total_visible") or len(seen_ids)),
            "total_unique_visible": int(state.get("total_unique_visible") or len(seen_ids)),
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
    previous_sources = previous.get("sources") if isinstance(previous.get("sources"), dict) else {}
    result_by_source = {result.platform: result for result in platform_results}
    visible_ids: dict[str, set[str]] = {}
    for assignment in assignments:
        result = result_by_source.get(assignment.platform)
        if result and result.status == "ok":
            visible_ids.setdefault(assignment.platform, set()).add(assignment.source_id)

    sources: dict[str, Any] = {}
    for result in platform_results:
        previous_state = (
            previous_sources.get(result.platform, {})
            if isinstance(previous_sources, dict)
            else {}
        )
        if result.status == "ok":
            seen_ids = sorted(visible_ids.get(result.platform, set()))
            sources[result.platform] = {
                "prefix": SOURCE_PREFIXES.get(result.platform, previous_state.get("prefix", "")),
                "seen_ids": seen_ids,
                "total_visible": result.count,
                "total_unique_visible": len(seen_ids),
            }
        else:
            sources[result.platform] = {
                "prefix": SOURCE_PREFIXES.get(result.platform, previous_state.get("prefix", "")),
                "seen_ids": list(previous_state.get("seen_ids") or []),
                "total_visible": int(previous_state.get("total_visible") or 0),
                "total_unique_visible": int(previous_state.get("total_unique_visible") or 0),
            }

    for source_key, prefix in SOURCE_PREFIXES.items():
        if source_key in sources:
            continue
        previous_state = (
            previous_sources.get(source_key, {}) if isinstance(previous_sources, dict) else {}
        )
        sources[source_key] = {
            "prefix": prefix,
            "seen_ids": list(previous_state.get("seen_ids") or []),
            "total_visible": int(previous_state.get("total_visible") or 0),
            "total_unique_visible": int(previous_state.get("total_unique_visible") or 0),
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
