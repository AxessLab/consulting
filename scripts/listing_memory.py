"""Persistent per-source dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import DEFAULT_PLATFORMS, SOURCE_REGISTRY, AssignmentRecord, PlatformScanResult

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEMORY_PATH = REPO_ROOT / "assignment-listing-seen.json"


def _empty_source_state(source_key: str) -> dict[str, Any]:
    return {
        "prefix": SOURCE_REGISTRY[source_key].prefix,
        "seen_ids": [],
        "total_visible": 0,
        "total_unique_visible": 0,
    }


def collect_seen_ids_by_source(data: dict[str, Any]) -> dict[str, set[str]]:
    """Read bare per-source ids from current and legacy memory shapes."""
    seen: dict[str, set[str]] = {source_key: set() for source_key in DEFAULT_PLATFORMS}

    sources = data.get("sources")
    if isinstance(sources, dict):
        for source_key, state in sources.items():
            if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
                seen.setdefault(source_key, set()).update(str(item) for item in state["seen_ids"])

    # Older in-repo scripts briefly used "platforms" and seen_keys. Keep one-way
    # migration so a malformed local file does not cause a full repost.
    platforms = data.get("platforms")
    if isinstance(platforms, dict):
        for source_key, state in platforms.items():
            if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
                seen.setdefault(source_key, set()).update(str(item) for item in state["seen_ids"])

    if isinstance(data.get("seen_keys"), list):
        for key in data["seen_keys"]:
            source_key, _, source_id = str(key).partition(":")
            if source_key and source_id:
                seen.setdefault(source_key, set()).add(source_id)

    legacy_seen = data.get("seen_ids")
    if isinstance(legacy_seen, list):
        for source_id in legacy_seen:
            seen.setdefault("allakonsultuppdrag.se", set()).add(str(source_id))

    return seen


def collect_seen_keys(data: dict[str, Any]) -> set[str]:
    """Compatibility helper for old call sites that expect source:id keys."""
    return {
        f"{source_key}:{source_id}"
        for source_key, source_ids in collect_seen_ids_by_source(data).items()
        for source_id in source_ids
    }


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize memory to the unified sources shape used by cloud runs."""
    seen_by_source = collect_seen_ids_by_source(payload)
    normalized_sources: dict[str, Any] = {}

    raw_sources = payload.get("sources") if isinstance(payload.get("sources"), dict) else {}
    for source_key in DEFAULT_PLATFORMS:
        raw_state = raw_sources.get(source_key, {}) if isinstance(raw_sources, dict) else {}
        if not isinstance(raw_state, dict):
            raw_state = {}
        source_ids = sorted(seen_by_source.get(source_key, set()), key=str)
        normalized_sources[source_key] = {
            "prefix": raw_state.get("prefix") or SOURCE_REGISTRY[source_key].prefix,
            "seen_ids": source_ids,
            "total_visible": raw_state.get("total_visible", len(source_ids)),
            "total_unique_visible": raw_state.get("total_unique_visible", len(source_ids)),
        }

    normalized: dict[str, Any] = {
        "last_scan_at": payload.get("last_scan_at"),
        "scan_date": payload.get("scan_date"),
        "sources": normalized_sources,
    }
    return normalized


def load_memory(path: Path) -> tuple[dict[str, set[str]], dict[str, Any]]:
    if not path.is_file() or path.stat().st_size == 0:
        return {source_key: set() for source_key in DEFAULT_PLATFORMS}, {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {source_key: set() for source_key in DEFAULT_PLATFORMS}, {}

    return collect_seen_ids_by_source(data), data


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
        source_key: {
            **_empty_source_state(source_key),
            **previous.get("sources", {}).get(source_key, {}),
        }
        for source_key in DEFAULT_PLATFORMS
    }

    ids_by_source: dict[str, set[str]] = {}
    for assignment in assignments:
        ids_by_source.setdefault(assignment.source_key, set()).add(assignment.source_id)

    for result in platform_results:
        if result.status != "ok":
            continue
        source_ids = sorted(ids_by_source.get(result.platform, set()), key=str)
        prefix = SOURCE_REGISTRY.get(result.platform)
        sources[result.platform] = {
            "prefix": prefix.prefix if prefix else "",
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
