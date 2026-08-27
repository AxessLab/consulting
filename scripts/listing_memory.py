"""Persistent dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import SOURCE_PREFIXES, AssignmentRecord, PlatformScanResult

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEMORY_PATH = REPO_ROOT / "assignment-listing-seen.json"


def _blank_source_state(source_key: str) -> dict[str, Any]:
    return {
        "prefix": SOURCE_PREFIXES.get(source_key, ""),
        "seen_ids": [],
        "total_visible": 0,
        "total_unique_visible": 0,
    }


def collect_seen_ids_by_source(data: dict[str, Any]) -> dict[str, set[str]]:
    """Read per-source seen ids from current and legacy memory shapes."""
    seen: dict[str, set[str]] = {source_key: set() for source_key in SOURCE_PREFIXES}

    sources = data.get("sources")
    if isinstance(sources, dict):
        for source_key, state in sources.items():
            if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
                seen.setdefault(source_key, set()).update(str(item) for item in state["seen_ids"])

    platforms = data.get("platforms")
    if isinstance(platforms, dict):
        for source_key, state in platforms.items():
            if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
                seen.setdefault(source_key, set()).update(str(item) for item in state["seen_ids"])

    if isinstance(data.get("seen_keys"), list):
        for item in data["seen_keys"]:
            source_key, sep, source_id = str(item).partition(":")
            if sep and source_id:
                seen.setdefault(source_key, set()).add(source_id)

    legacy_seen = data.get("seen_ids")
    if isinstance(legacy_seen, list):
        seen.setdefault("allakonsultuppdrag.se", set()).update(
            str(source_id) for source_id in legacy_seen
        )

    return seen


def collect_seen_keys(data: dict[str, Any]) -> set[str]:
    """Return dedupe keys in source_key:source_id form for compatibility."""
    seen_keys: set[str] = set()
    for source_key, ids in collect_seen_ids_by_source(data).items():
        seen_keys.update(f"{source_key}:{source_id}" for source_id in ids)
    return seen_keys


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize any supported memory shape to the unified sources object."""
    seen_by_source = collect_seen_ids_by_source(payload)
    raw_sources = payload.get("sources") if isinstance(payload.get("sources"), dict) else {}
    raw_platforms = payload.get("platforms") if isinstance(payload.get("platforms"), dict) else {}

    sources: dict[str, Any] = {}
    for source_key, prefix in SOURCE_PREFIXES.items():
        existing: dict[str, Any] = {}
        if isinstance(raw_sources.get(source_key), dict):
            existing = raw_sources[source_key]
        elif isinstance(raw_platforms.get(source_key), dict):
            existing = raw_platforms[source_key]
        seen_ids = sorted(seen_by_source.get(source_key, set()))
        sources[source_key] = {
            "prefix": str(existing.get("prefix") or prefix),
            "seen_ids": seen_ids,
            "total_visible": int(existing.get("total_visible") or len(seen_ids)),
            "total_unique_visible": int(existing.get("total_unique_visible") or len(seen_ids)),
        }

    for source_key, ids in seen_by_source.items():
        if source_key in sources:
            continue
        seen_ids = sorted(ids)
        sources[source_key] = {
            "prefix": "",
            "seen_ids": seen_ids,
            "total_visible": len(seen_ids),
            "total_unique_visible": len(seen_ids),
        }

    total_visible = sum(int(state.get("total_visible") or 0) for state in sources.values())
    total_unique_visible = sum(
        int(state.get("total_unique_visible") or 0) for state in sources.values()
    )

    return {
        "last_scan_at": payload.get("last_scan_at"),
        "scan_date": payload.get("scan_date"),
        "sources": sources,
        "total_visible": total_visible,
        "total_unique_visible": total_unique_visible,
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
    existing_memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    existing = normalize_memory_payload(existing_memory or {})
    sources: dict[str, Any] = {
        source_key: dict(existing.get("sources", {}).get(source_key) or _blank_source_state(source_key))
        for source_key in SOURCE_PREFIXES
    }
    visible_ids: dict[str, set[str]] = {source_key: set() for source_key in SOURCE_PREFIXES}
    for assignment in assignments:
        visible_ids.setdefault(assignment.source_key, set()).add(str(assignment.source_id))

    for result in platform_results:
        source_key = result.platform
        if result.status != "ok":
            continue
        ids = sorted(visible_ids.get(source_key, set()))
        sources[source_key] = {
            "prefix": SOURCE_PREFIXES.get(source_key, ""),
            "seen_ids": ids,
            "total_visible": result.count,
            "total_unique_visible": len(ids),
        }

    return {
        "last_scan_at": now,
        "scan_date": scan_date.isoformat(),
        "sources": sources,
        "total_visible": sum(int(state.get("total_visible") or 0) for state in sources.values()),
        "total_unique_visible": sum(
            int(state.get("total_unique_visible") or 0) for state in sources.values()
        ),
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
