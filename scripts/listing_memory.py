"""Persistent per-source dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import (
    DEFAULT_PLATFORMS,
    SOURCE_PREFIXES,
    AssignmentRecord,
    PlatformScanResult,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEMORY_PATH = REPO_ROOT / "assignment-listing-seen.json"


def default_source_state(source_key: str) -> dict[str, Any]:
    return {
        "prefix": SOURCE_PREFIXES[source_key],
        "seen_ids": [],
        "total_visible": 0,
        "total_unique_visible": 0,
    }


def source_seen_ids(data: dict[str, Any]) -> dict[str, set[str]]:
    """Read per-source bare IDs from current and legacy memory shapes."""
    seen_by_source: dict[str, set[str]] = {source: set() for source in DEFAULT_PLATFORMS}

    sources = data.get("sources")
    if isinstance(sources, dict):
        for source_key, state in sources.items():
            if not isinstance(state, dict) or not isinstance(state.get("seen_ids"), list):
                continue
            seen_by_source.setdefault(source_key, set()).update(
                str(source_id) for source_id in state["seen_ids"]
            )

    # Previous repo shape: one flat dedupe-key list.
    if isinstance(data.get("seen_keys"), list):
        for key in data["seen_keys"]:
            source_key, sep, source_id = str(key).partition(":")
            if sep:
                seen_by_source.setdefault(source_key, set()).add(source_id)

    # Transitional shape used "platforms" for source state.
    platforms = data.get("platforms")
    if isinstance(platforms, dict):
        for source_key, state in platforms.items():
            if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
                seen_by_source.setdefault(source_key, set()).update(
                    str(source_id) for source_id in state["seen_ids"]
                )

    # Legacy single-source shape.
    if isinstance(data.get("seen_ids"), list):
        seen_by_source.setdefault("allakonsultuppdrag.se", set()).update(
            str(source_id) for source_id in data["seen_ids"]
        )

    return seen_by_source


def collect_seen_keys(data: dict[str, Any]) -> set[str]:
    """Read source-prefixed dedupe keys from current or legacy memory shapes."""
    return {
        f"{source_key}:{source_id}"
        for source_key, ids in source_seen_ids(data).items()
        for source_id in ids
    }


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the unified `sources` memory shape, migrating older payloads."""
    seen_by_source = source_seen_ids(payload)
    raw_sources = payload.get("sources") if isinstance(payload.get("sources"), dict) else {}
    sources: dict[str, Any] = {}
    for source_key in DEFAULT_PLATFORMS:
        state = raw_sources.get(source_key) if isinstance(raw_sources, dict) else None
        state = state if isinstance(state, dict) else {}
        seen_ids = sorted(seen_by_source.get(source_key, set()), key=str)
        sources[source_key] = {
            "prefix": state.get("prefix") or SOURCE_PREFIXES[source_key],
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
    sources: dict[str, Any] = {
        source_key: dict(previous.get("sources", {}).get(source_key, default_source_state(source_key)))
        for source_key in DEFAULT_PLATFORMS
    }
    ids_by_source: dict[str, set[str]] = {source: set() for source in DEFAULT_PLATFORMS}
    for assignment in assignments:
        ids_by_source.setdefault(assignment.source_key, set()).add(assignment.source_id)

    for result in platform_results:
        if result.status != "ok":
            continue
        seen_ids = sorted(ids_by_source.get(result.source_key, set()), key=str)
        sources[result.source_key] = {
            "prefix": SOURCE_PREFIXES[result.source_key],
            "seen_ids": seen_ids,
            "total_visible": result.count,
            "total_unique_visible": len(seen_ids),
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
