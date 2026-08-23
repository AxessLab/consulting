"""Persistent dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import (
    ACTIVE_PLATFORM_ORDER,
    PLATFORM_PREFIXES,
    AssignmentRecord,
    PlatformScanResult,
)

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


def _empty_source_state(source_key: str) -> dict[str, Any]:
    return {
        "prefix": PLATFORM_PREFIXES.get(source_key, ""),
        "seen_ids": [],
        "total_visible": 0,
        "total_unique_visible": 0,
    }


def _copy_source_state(source_key: str, raw_state: dict[str, Any]) -> dict[str, Any]:
    state = _empty_source_state(source_key)
    if raw_state.get("prefix"):
        state["prefix"] = str(raw_state["prefix"])
    seen_ids = raw_state.get("seen_ids")
    if isinstance(seen_ids, list):
        state["seen_ids"] = sorted({str(item) for item in seen_ids})
    if isinstance(raw_state.get("total_visible"), int):
        state["total_visible"] = raw_state["total_visible"]
    if isinstance(raw_state.get("total_unique_visible"), int):
        state["total_unique_visible"] = raw_state["total_unique_visible"]
    elif isinstance(raw_state.get("total_visible"), int):
        state["total_unique_visible"] = raw_state["total_visible"]
    return state


def _source_states_from_payload(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sources: dict[str, dict[str, Any]] = {}

    raw_sources = payload.get("sources")
    if isinstance(raw_sources, dict):
        for source_key, state in raw_sources.items():
            if isinstance(state, dict):
                sources[source_key] = _copy_source_state(source_key, state)

    raw_platforms = payload.get("platforms")
    if isinstance(raw_platforms, dict):
        for source_key, state in raw_platforms.items():
            if not isinstance(state, dict):
                continue
            if isinstance(state.get("seen_ids"), list):
                sources[source_key] = _copy_source_state(source_key, state)
            elif source_key not in sources:
                sources[source_key] = _empty_source_state(source_key)
                if isinstance(state.get("total_visible"), int):
                    sources[source_key]["total_visible"] = state["total_visible"]
                    sources[source_key]["total_unique_visible"] = state["total_visible"]

    grouped_seen: dict[str, set[str]] = {}
    for key in payload.get("seen_keys") or []:
        if not isinstance(key, str) or ":" not in key:
            continue
        source_key, source_id = key.split(":", 1)
        grouped_seen.setdefault(source_key, set()).add(source_id)
    for source_key, seen_ids in grouped_seen.items():
        state = sources.setdefault(source_key, _empty_source_state(source_key))
        state["seen_ids"] = sorted(set(state["seen_ids"]) | seen_ids)
        if not state["total_visible"]:
            state["total_visible"] = len(state["seen_ids"])
        if not state["total_unique_visible"]:
            state["total_unique_visible"] = len(state["seen_ids"])

    legacy_seen = payload.get("seen_ids")
    if isinstance(legacy_seen, list):
        state = sources.setdefault(
            "allakonsultuppdrag.se",
            _empty_source_state("allakonsultuppdrag.se"),
        )
        state["seen_ids"] = sorted(set(state["seen_ids"]) | {str(item) for item in legacy_seen})
        if not state["total_visible"]:
            state["total_visible"] = len(state["seen_ids"])
        if not state["total_unique_visible"]:
            state["total_unique_visible"] = len(state["seen_ids"])

    for source_key in ACTIVE_PLATFORM_ORDER:
        sources.setdefault(source_key, _empty_source_state(source_key))

    return sources


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize current and legacy memory shapes into the unified sources object."""
    sources = _source_states_from_payload(payload)

    normalized: dict[str, Any] = {
        "last_scan_at": payload.get("last_scan_at"),
        "scan_date": payload.get("scan_date"),
        "sources": {
            source_key: sources[source_key]
            for source_key in sorted(
                sources,
                key=lambda key: (
                    ACTIVE_PLATFORM_ORDER.index(key)
                    if key in ACTIVE_PLATFORM_ORDER
                    else len(ACTIVE_PLATFORM_ORDER),
                    key,
                ),
            )
        },
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
    previous_sources = _source_states_from_payload(previous_memory or {})
    sources = {
        source_key: _copy_source_state(source_key, state)
        for source_key, state in previous_sources.items()
    }
    assignments_by_platform: dict[str, set[str]] = {}
    for assignment in assignments:
        assignments_by_platform.setdefault(assignment.platform, set()).add(assignment.source_id)

    for result in platform_results:
        sources.setdefault(result.platform, _empty_source_state(result.platform))
        if result.status != "ok":
            continue
        seen_ids = sorted(assignments_by_platform.get(result.platform, set()))
        sources[result.platform] = {
            "prefix": PLATFORM_PREFIXES.get(result.platform, ""),
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
