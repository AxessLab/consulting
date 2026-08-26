"""Persistent dedupe memory for assignment listing runs."""

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


def collect_seen_ids_by_source(data: dict[str, Any]) -> dict[str, set[str]]:
    seen: dict[str, set[str]] = {source_key: set() for source_key in DEFAULT_PLATFORMS}
    for key in collect_seen_keys(data):
        if ":" not in key:
            continue
        source_key, source_id = key.split(":", 1)
        seen.setdefault(source_key, set()).add(source_id)
    return seen


def _previous_source_state(payload: dict[str, Any], source_key: str) -> dict[str, Any]:
    sources = payload.get("sources")
    if isinstance(sources, dict) and isinstance(sources.get(source_key), dict):
        state = dict(sources[source_key])
        state.setdefault("prefix", SOURCE_PREFIXES.get(source_key, ""))
        state.setdefault("seen_ids", [])
        state.setdefault("total_visible", len(state.get("seen_ids") or []))
        state.setdefault("total_unique_visible", len(set(state.get("seen_ids") or [])))
        return state

    platforms = payload.get("platforms")
    if isinstance(platforms, dict) and isinstance(platforms.get(source_key), dict):
        state = platforms[source_key]
        seen_ids = [
            key.split(":", 1)[1]
            for key in sorted(collect_seen_keys(payload))
            if key.startswith(f"{source_key}:")
        ]
        return {
            "prefix": SOURCE_PREFIXES.get(source_key, ""),
            "seen_ids": seen_ids,
            "total_visible": state.get("total_visible", len(seen_ids)),
            "total_unique_visible": state.get("total_unique_visible", len(set(seen_ids))),
        }

    return {
        "prefix": SOURCE_PREFIXES.get(source_key, ""),
        "seen_ids": [],
        "total_visible": 0,
        "total_unique_visible": 0,
    }


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize current and legacy memory into the unified per-source shape."""
    sources: dict[str, Any] = {}
    for source_key in DEFAULT_PLATFORMS:
        state = _previous_source_state(payload, source_key)
        seen_ids = sorted({str(item) for item in state.get("seen_ids") or []})
        sources[source_key] = {
            "prefix": SOURCE_PREFIXES.get(source_key, ""),
            "seen_ids": seen_ids,
            "total_visible": int(state.get("total_visible") or len(seen_ids)),
            "total_unique_visible": int(
                state.get("total_unique_visible") or len(seen_ids)
            ),
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
    previous_memory = previous_memory or {}
    seen_by_source: dict[str, set[str]] = {source_key: set() for source_key in DEFAULT_PLATFORMS}
    for assignment in assignments:
        seen_by_source.setdefault(assignment.platform, set()).add(str(assignment.source_id))

    result_by_source = {result.platform: result for result in platform_results}
    sources: dict[str, Any] = {}
    for source_key in DEFAULT_PLATFORMS:
        previous = _previous_source_state(previous_memory, source_key)
        result = result_by_source.get(source_key)
        if result is not None and result.status == "ok":
            visible_ids = sorted(seen_by_source.get(source_key, set()))
            sources[source_key] = {
                "prefix": SOURCE_PREFIXES.get(source_key, ""),
                "seen_ids": visible_ids,
                "total_visible": result.count,
                "total_unique_visible": len(visible_ids),
            }
        else:
            sources[source_key] = previous

    return {
        "last_scan_at": now,
        "scan_date": scan_date.isoformat(),
        "sources": sources,
    }


def build_source_stats(
    *,
    assignments: list[AssignmentRecord],
    platform_results: list[PlatformScanResult],
    previous_memory: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    seen_by_source = collect_seen_ids_by_source(previous_memory)
    visible_by_source: dict[str, set[str]] = {source_key: set() for source_key in DEFAULT_PLATFORMS}
    for assignment in assignments:
        visible_by_source.setdefault(assignment.platform, set()).add(str(assignment.source_id))

    stats: dict[str, dict[str, Any]] = {}
    for result in platform_results:
        visible_ids = visible_by_source.get(result.platform, set())
        previous_seen = seen_by_source.get(result.platform, set())
        stats[result.platform] = {
            "status": result.status,
            "total_visible": result.count,
            "total_unique_visible": len(visible_ids),
            "new_ids": len(visible_ids - previous_seen),
        }
        if result.message:
            stats[result.platform]["message"] = result.message
    return stats


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
