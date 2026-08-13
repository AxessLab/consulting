"""Persistent dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import AssignmentRecord, PlatformScanResult, SOURCE_PREFIXES

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEMORY_PATH = REPO_ROOT / "assignment-listing-seen.json"


def _source_sort_key(source_id: str) -> tuple[int, int | str]:
    if source_id.isdigit():
        return (0, int(source_id))
    return (1, source_id)


def collect_seen_ids_by_source(data: dict[str, Any]) -> dict[str, set[str]]:
    """Read bare source ids from current and legacy memory shapes."""
    seen_ids: dict[str, set[str]] = {}

    sources = data.get("sources")
    if isinstance(sources, dict):
        for source_key, state in sources.items():
            if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
                seen_ids.setdefault(source_key, set()).update(
                    str(item) for item in state["seen_ids"]
                )

    if isinstance(data.get("seen_keys"), list):
        for item in data["seen_keys"]:
            key = str(item)
            if ":" in key:
                source_key, source_id = key.split(":", 1)
                seen_ids.setdefault(source_key, set()).add(source_id)

    platforms = data.get("platforms")
    if isinstance(platforms, dict):
        for platform_id, state in platforms.items():
            if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
                for source_id in state["seen_ids"]:
                    seen_ids.setdefault(platform_id, set()).add(str(source_id))

    legacy_seen = data.get("seen_ids")
    if isinstance(legacy_seen, list):
        for source_id in legacy_seen:
            seen_ids.setdefault("allakonsultuppdrag.se", set()).add(str(source_id))

    return seen_ids


def collect_seen_keys(data: dict[str, Any]) -> set[str]:
    """Read seen dedupe keys from current or legacy memory shapes."""
    seen_keys: set[str] = set()
    for source_key, source_ids in collect_seen_ids_by_source(data).items():
        for source_id in source_ids:
            seen_keys.add(f"{source_key}:{source_id}")

    return seen_keys


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize memory to the current per-source seen_id shape."""
    source_ids = collect_seen_ids_by_source(payload)
    raw_sources = payload.get("sources") if isinstance(payload.get("sources"), dict) else {}
    raw_platforms = payload.get("platforms") if isinstance(payload.get("platforms"), dict) else {}
    all_sources = list(dict.fromkeys([*SOURCE_PREFIXES.keys(), *source_ids.keys()]))
    sources: dict[str, Any] = {}
    for source_key in all_sources:
        raw_state = {}
        if isinstance(raw_sources, dict) and isinstance(raw_sources.get(source_key), dict):
            raw_state = raw_sources[source_key]
        elif isinstance(raw_platforms, dict) and isinstance(raw_platforms.get(source_key), dict):
            raw_state = raw_platforms[source_key]
        ids = sorted(source_ids.get(source_key, set()), key=_source_sort_key)
        sources[source_key] = {
            "prefix": raw_state.get("prefix") or SOURCE_PREFIXES.get(source_key, ""),
            "seen_ids": ids,
            "total_visible": raw_state.get("total_visible", len(ids)),
            "total_unique_visible": raw_state.get("total_unique_visible", len(ids)),
        }

    normalized: dict[str, Any] = {
        "source": payload.get("source", "multi-platform assignment listing"),
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
    previous_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    previous = normalize_memory_payload(previous_data or {})
    sources: dict[str, Any] = dict(previous.get("sources") or {})
    ids_by_source: dict[str, set[str]] = {}
    for assignment in assignments:
        ids_by_source.setdefault(assignment.platform, set()).add(assignment.source_id)

    for result in platform_results:
        if result.status != "ok":
            sources.setdefault(
                result.platform,
                {
                    "prefix": SOURCE_PREFIXES.get(result.platform, ""),
                    "seen_ids": [],
                    "total_visible": 0,
                    "total_unique_visible": 0,
                },
            )
            continue
        ids = sorted(ids_by_source.get(result.platform, set()), key=_source_sort_key)
        sources[result.platform] = {
            "prefix": SOURCE_PREFIXES.get(result.platform, ""),
            "seen_ids": ids,
            "total_visible": result.count,
            "total_unique_visible": len(ids),
        }

    return {
        "source": "multi-platform assignment listing",
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
