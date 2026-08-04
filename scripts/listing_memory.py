"""Persistent dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import AssignmentRecord, PlatformScanResult, SOURCE_REGISTRY, source_prefix

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEMORY_PATH = REPO_ROOT / "assignment-listing-seen.json"


def empty_source_state(source_key: str) -> dict[str, Any]:
    return {
        "prefix": source_prefix(source_key),
        "seen_ids": [],
        "total_visible": 0,
        "total_unique_visible": 0,
    }


def collect_seen_ids_by_source(data: dict[str, Any]) -> dict[str, set[str]]:
    """Read bare source ids from current and legacy memory shapes."""
    seen_ids: dict[str, set[str]] = {source_key: set() for source_key in SOURCE_REGISTRY}

    sources = data.get("sources")
    if isinstance(sources, dict):
        for source_key, state in sources.items():
            if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
                seen_ids.setdefault(source_key, set()).update(
                    str(item) for item in state["seen_ids"]
                )

    if isinstance(data.get("seen_keys"), list):
        for item in data["seen_keys"]:
            source_key, sep, source_id = str(item).partition(":")
            if sep and source_id:
                seen_ids.setdefault(source_key, set()).add(source_id)

    platforms = data.get("platforms")
    if isinstance(platforms, dict):
        for source_key, state in platforms.items():
            if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
                seen_ids.setdefault(source_key, set()).update(
                    str(item) for item in state["seen_ids"]
                )

    legacy_seen = data.get("seen_ids")
    if isinstance(legacy_seen, list):
        seen_ids.setdefault("allakonsultuppdrag.se", set()).update(
            str(item) for item in legacy_seen
        )

    return seen_ids


def collect_seen_keys(data: dict[str, Any]) -> set[str]:
    """Read seen dedupe keys from current or legacy memory shapes."""
    seen_keys: set[str] = set()
    for source_key, source_ids in collect_seen_ids_by_source(data).items():
        seen_keys.update(f"{source_key}:{source_id}" for source_id in source_ids)
    return seen_keys


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize memory to the unified per-source seen-id shape."""
    seen_ids = collect_seen_ids_by_source(payload)
    raw_sources = payload.get("sources")
    sources: dict[str, Any] = {}

    for source_key, registry_entry in SOURCE_REGISTRY.items():
        raw_state = raw_sources.get(source_key) if isinstance(raw_sources, dict) else None
        ids = sorted(seen_ids.get(source_key, set()), key=str)
        total_visible = len(ids)
        total_unique_visible = len(ids)
        if isinstance(raw_state, dict):
            total_visible = raw_state.get("total_visible", total_visible)
            total_unique_visible = raw_state.get("total_unique_visible", total_unique_visible)
        sources[source_key] = {
            "prefix": str(registry_entry.get("prefix", source_prefix(source_key))),
            "seen_ids": ids,
            "total_visible": total_visible,
            "total_unique_visible": total_unique_visible,
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
    sources: dict[str, Any] = {
        source_key: dict(state)
        for source_key, state in (previous.get("sources") or {}).items()
        if isinstance(state, dict)
    }
    for source_key in SOURCE_REGISTRY:
        sources.setdefault(source_key, empty_source_state(source_key))

    visible_ids: dict[str, set[str]] = {}
    for assignment in assignments:
        visible_ids.setdefault(assignment.platform, set()).add(assignment.source_id)

    for result in platform_results:
        if result.status != "ok":
            # A source failure must not erase prior seen ids for that source.
            continue
        source_ids = sorted(visible_ids.get(result.platform, set()), key=str)
        sources[result.platform] = {
            "prefix": source_prefix(result.platform),
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
