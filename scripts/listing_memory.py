"""Persistent dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import SOURCE_REGISTRY, AssignmentRecord, PlatformScanResult, source_prefix

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
        "prefix": source_prefix(source_key),
        "seen_ids": [],
        "total_visible": 0,
        "total_unique_visible": 0,
    }


def _source_states_from_seen_keys(seen_keys: set[str]) -> dict[str, dict[str, Any]]:
    states: dict[str, dict[str, Any]] = {}
    for key in sorted(seen_keys):
        if ":" not in key:
            continue
        source_key, source_id = key.split(":", 1)
        state = states.setdefault(source_key, _empty_source_state(source_key))
        state["seen_ids"].append(source_id)
    for state in states.values():
        state["seen_ids"] = sorted(set(str(item) for item in state["seen_ids"]))
        state["total_visible"] = len(state["seen_ids"])
        state["total_unique_visible"] = len(state["seen_ids"])
    return states


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize current and legacy payloads to the per-source seen-id shape."""
    seen_keys = collect_seen_keys(payload)
    sources = _source_states_from_seen_keys(seen_keys)

    raw_sources = payload.get("sources")
    if isinstance(raw_sources, dict):
        for source_key, state in raw_sources.items():
            if not isinstance(state, dict):
                continue
            seen_ids = [str(item) for item in state.get("seen_ids") or []]
            sources[source_key] = {
                "prefix": str(state.get("prefix") or source_prefix(source_key)),
                "seen_ids": sorted(set(seen_ids)),
                "total_visible": int(state.get("total_visible") or len(seen_ids)),
                "total_unique_visible": int(
                    state.get("total_unique_visible") or len(set(seen_ids))
                ),
            }

    for source_key in SOURCE_REGISTRY:
        sources.setdefault(source_key, _empty_source_state(source_key))

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
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    by_source: dict[str, dict[str, AssignmentRecord]] = {}
    successful_sources = {
        result.platform for result in platform_results if result.status == "ok"
    }
    for assignment in assignments:
        if assignment.source_key not in successful_sources:
            continue
        by_source.setdefault(assignment.source_key, {})[assignment.source_id] = assignment

    sources: dict[str, Any] = {}
    for result in platform_results:
        if result.status != "ok":
            continue
        source_ids = sorted(by_source.get(result.platform, {}))
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
        "updated_sources": sorted(successful_sources),
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
    current: dict[str, Any] = {}
    if memory_path.is_file() and memory_path.stat().st_size > 0:
        try:
            current = json.loads(memory_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            current = {}
    merged = normalize_memory_payload(current)
    update_sources = memory_update.get("updated_sources")
    if not isinstance(update_sources, list):
        update_sources = list((memory_update.get("sources") or {}).keys())
    for source_key in update_sources:
        state = (memory_update.get("sources") or {}).get(source_key)
        if isinstance(state, dict):
            merged["sources"][source_key] = {
                "prefix": str(state.get("prefix") or source_prefix(source_key)),
                "seen_ids": sorted(set(str(item) for item in state.get("seen_ids") or [])),
                "total_visible": int(state.get("total_visible") or 0),
                "total_unique_visible": int(state.get("total_unique_visible") or 0),
            }
    merged["last_scan_at"] = memory_update.get("last_scan_at")
    merged["scan_date"] = memory_update.get("scan_date")
    write_memory_file(memory_path, merged)


def read_memory_export(memory_path: Path) -> str:
    if not memory_path.is_file() or memory_path.stat().st_size == 0:
        return ""
    return memory_path.read_text(encoding="utf-8")
