"""Persistent per-source dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import AssignmentRecord, PlatformScanResult, SOURCE_REGISTRY

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEMORY_PATH = REPO_ROOT / "assignment-listing-seen.json"


def _prefix_for_source(source_key: str) -> str:
    return SOURCE_REGISTRY.get(source_key, {}).get("prefix", "")


def collect_seen_by_source(data: dict[str, Any]) -> dict[str, set[str]]:
    """Read per-source seen ids from current and legacy memory shapes."""
    seen_by_source: dict[str, set[str]] = {
        source_key: set() for source_key in SOURCE_REGISTRY
    }

    sources = data.get("sources")
    if isinstance(sources, dict):
        for source_key, state in sources.items():
            if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
                seen_by_source.setdefault(source_key, set()).update(
                    str(item) for item in state["seen_ids"]
                )

    # Earlier iterations stored either platform metadata with seen_ids or a flat
    # list of "platform:id" keys. Import them so old cloud memories remain useful.
    platforms = data.get("platforms")
    if isinstance(platforms, dict):
        for source_key, state in platforms.items():
            if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
                seen_by_source.setdefault(source_key, set()).update(
                    str(item) for item in state["seen_ids"]
                )

    if isinstance(data.get("seen_keys"), list):
        for key in data["seen_keys"]:
            source_key, sep, source_id = str(key).partition(":")
            if sep and source_id:
                seen_by_source.setdefault(source_key, set()).add(source_id)

    legacy_seen = data.get("seen_ids")
    if isinstance(legacy_seen, list):
        seen_by_source.setdefault("allakonsultuppdrag.se", set()).update(
            str(source_id) for source_id in legacy_seen
        )

    return seen_by_source


def collect_seen_keys(data: dict[str, Any]) -> set[str]:
    """Read seen dedupe keys from current or legacy memory shapes."""
    seen_keys: set[str] = set()
    for source_key, seen_ids in collect_seen_by_source(data).items():
        for source_id in seen_ids:
            seen_keys.add(f"{source_key}:{source_id}")
    return seen_keys


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize memory into the unified `sources.*.seen_ids` shape."""
    seen_by_source = collect_seen_by_source(payload)
    raw_sources = payload.get("sources") if isinstance(payload.get("sources"), dict) else {}
    normalized_sources: dict[str, Any] = {}

    for source_key, meta in SOURCE_REGISTRY.items():
        raw_state = raw_sources.get(source_key) if isinstance(raw_sources, dict) else {}
        raw_state = raw_state if isinstance(raw_state, dict) else {}
        seen_ids = sorted(seen_by_source.get(source_key, set()))
        normalized_sources[source_key] = {
            "prefix": meta["prefix"],
            "seen_ids": seen_ids,
            "total_visible": raw_state.get("total_visible", len(seen_ids)),
            "total_unique_visible": raw_state.get("total_unique_visible", len(seen_ids)),
        }

    return {
        "last_scan_at": payload.get("last_scan_at"),
        "scan_date": payload.get("scan_date"),
        "sources": normalized_sources,
    }


def load_memory(path: Path) -> tuple[set[str], dict[str, Any]]:
    if not path.is_file() or path.stat().st_size == 0:
        return set(), {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set(), {}

    return collect_seen_keys(data), data


def load_seen_by_source(path: Path) -> tuple[dict[str, set[str]], dict[str, Any]]:
    if not path.is_file() or path.stat().st_size == 0:
        return {source_key: set() for source_key in SOURCE_REGISTRY}, {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {source_key: set() for source_key in SOURCE_REGISTRY}, {}

    return collect_seen_by_source(data), data


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

    visible_ids_by_source: dict[str, set[str]] = {source_key: set() for source_key in SOURCE_REGISTRY}
    for assignment in assignments:
        visible_ids_by_source.setdefault(assignment.source_key, set()).add(assignment.source_id)

    for result in platform_results:
        if result.status != "ok":
            continue
        source_key = result.source_key
        visible_ids = sorted(visible_ids_by_source.get(source_key, set()))
        sources[source_key] = {
            "prefix": _prefix_for_source(source_key),
            "seen_ids": visible_ids,
            "total_visible": result.count,
            "total_unique_visible": len(visible_ids),
        }

    for source_key, meta in SOURCE_REGISTRY.items():
        sources.setdefault(
            source_key,
            {
                "prefix": meta["prefix"],
                "seen_ids": [],
                "total_visible": 0,
                "total_unique_visible": 0,
            },
        )

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
