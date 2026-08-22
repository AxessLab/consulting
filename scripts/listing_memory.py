"""Persistent dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import AssignmentRecord, PlatformScanResult, SOURCE_REGISTRY

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


def source_seen_ids(data: dict[str, Any], source_key: str) -> set[str]:
    sources = data.get("sources")
    if isinstance(sources, dict):
        state = sources.get(source_key)
        if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
            return {str(item) for item in state["seen_ids"]}

    platforms = data.get("platforms")
    if isinstance(platforms, dict):
        state = platforms.get(source_key)
        if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
            return {str(item) for item in state["seen_ids"]}

    if source_key == "allakonsultuppdrag.se" and isinstance(data.get("seen_ids"), list):
        return {str(item) for item in data["seen_ids"]}

    return set()


def source_seen_ids_by_platform(data: dict[str, Any]) -> dict[str, set[str]]:
    return {source_key: source_seen_ids(data, source_key) for source_key in SOURCE_REGISTRY}


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize current and legacy memory into the unified per-source shape."""
    sources: dict[str, Any] = {}
    raw_sources = payload.get("sources")
    if isinstance(raw_sources, dict):
        for source_key, registry in SOURCE_REGISTRY.items():
            state = raw_sources.get(source_key)
            if isinstance(state, dict):
                seen_ids = [str(item) for item in state.get("seen_ids", [])]
                sources[source_key] = {
                    "prefix": registry["prefix"],
                    "seen_ids": sorted(set(seen_ids), key=lambda item: (len(item), item)),
                    "total_visible": int(state.get("total_visible") or len(set(seen_ids))),
                    "total_unique_visible": int(
                        state.get("total_unique_visible") or len(set(seen_ids))
                    ),
                }
            else:
                sources[source_key] = {
                    "prefix": registry["prefix"],
                    "seen_ids": sorted(source_seen_ids(payload, source_key)),
                    "total_visible": 0,
                    "total_unique_visible": 0,
                }
    else:
        for source_key, registry in SOURCE_REGISTRY.items():
            seen_ids = source_seen_ids(payload, source_key)
            sources[source_key] = {
                "prefix": registry["prefix"],
                "seen_ids": sorted(seen_ids, key=lambda item: (len(item), item)),
                "total_visible": len(seen_ids),
                "total_unique_visible": len(seen_ids),
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
    previous_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    previous = normalize_memory_payload(previous_data or {})
    successful_sources = {result.platform for result in platform_results if result.status == "ok"}
    ids_by_source: dict[str, set[str]] = {}
    for assignment in assignments:
        ids_by_source.setdefault(assignment.platform, set()).add(str(assignment.source_id))

    sources: dict[str, Any] = {}
    previous_sources = previous.get("sources") if isinstance(previous.get("sources"), dict) else {}
    for source_key, registry in SOURCE_REGISTRY.items():
        if source_key in successful_sources:
            seen_ids = sorted(ids_by_source.get(source_key, set()), key=lambda item: (len(item), item))
            sources[source_key] = {
                "prefix": registry["prefix"],
                "seen_ids": seen_ids,
                "total_visible": len(seen_ids),
                "total_unique_visible": len(seen_ids),
            }
            continue

        previous_state = previous_sources.get(source_key) if isinstance(previous_sources, dict) else None
        if isinstance(previous_state, dict):
            sources[source_key] = {
                "prefix": registry["prefix"],
                "seen_ids": [str(item) for item in previous_state.get("seen_ids", [])],
                "total_visible": int(previous_state.get("total_visible") or 0),
                "total_unique_visible": int(previous_state.get("total_unique_visible") or 0),
            }
        else:
            sources[source_key] = {
                "prefix": registry["prefix"],
                "seen_ids": [],
                "total_visible": 0,
                "total_unique_visible": 0,
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
