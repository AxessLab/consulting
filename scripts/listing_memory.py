"""Persistent dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import (
    ACTIVE_SOURCE_ORDER,
    SOURCE_PREFIXES,
    AssignmentRecord,
    PlatformScanResult,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEMORY_PATH = REPO_ROOT / "assignment-listing-seen.json"


def collect_seen_ids_by_source(data: dict[str, Any]) -> dict[str, set[str]]:
    """Read bare source ids from current and legacy memory shapes."""
    seen_ids: dict[str, set[str]] = {source: set() for source in ACTIVE_SOURCE_ORDER}

    sources = data.get("sources")
    if isinstance(sources, dict):
        for source_key, state in sources.items():
            if not isinstance(state, dict) or not isinstance(state.get("seen_ids"), list):
                continue
            seen_ids.setdefault(source_key, set()).update(str(item) for item in state["seen_ids"])

    if isinstance(data.get("seen_keys"), list):
        for key in data["seen_keys"]:
            source_key, _, source_id = str(key).partition(":")
            if source_key and source_id:
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
    for source_key, ids in collect_seen_ids_by_source(data).items():
        seen_keys.update(f"{source_key}:{source_id}" for source_id in ids)

    return seen_keys


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize dedupe memory to the unified per-source shape."""
    seen_ids = collect_seen_ids_by_source(payload)
    raw_sources = payload.get("sources") if isinstance(payload.get("sources"), dict) else {}
    sources: dict[str, Any] = {}

    for source_key in ACTIVE_SOURCE_ORDER:
        state = raw_sources.get(source_key, {}) if isinstance(raw_sources, dict) else {}
        state = state if isinstance(state, dict) else {}
        ids = (
            [str(item) for item in state.get("seen_ids", [])]
            if isinstance(state.get("seen_ids"), list)
            else sorted(seen_ids.get(source_key, set()))
        )
        unique_ids = sorted(set(ids))
        sources[source_key] = {
            "prefix": state.get("prefix") or SOURCE_PREFIXES[source_key],
            "seen_ids": unique_ids,
            "total_visible": state.get("total_visible", len(unique_ids)),
            "total_unique_visible": state.get("total_unique_visible", len(unique_ids)),
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
    previous_memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    payload = normalize_memory_payload(previous_memory or {})
    sources = payload["sources"]
    ids_by_source: dict[str, set[str]] = {source: set() for source in ACTIVE_SOURCE_ORDER}
    for assignment in assignments:
        ids_by_source.setdefault(assignment.source_key, set()).add(assignment.source_id)

    for result in platform_results:
        if result.status != "ok":
            continue
        source_key = result.platform
        if source_key not in SOURCE_PREFIXES:
            continue
        source_ids = sorted(ids_by_source.get(source_key, set()))
        sources[source_key] = {
            "prefix": SOURCE_PREFIXES[source_key],
            "seen_ids": source_ids,
            "total_visible": result.count,
            "total_unique_visible": len(source_ids),
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
