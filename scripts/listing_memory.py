"""Persistent dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import SOURCE_REGISTRY, AssignmentRecord, PlatformScanResult

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


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize current and legacy memory into the unified per-source shape."""
    seen_keys = collect_seen_keys(payload)
    sources: dict[str, Any] = {}
    raw_sources = payload.get("sources")
    for source_key, meta in SOURCE_REGISTRY.items():
        previous = raw_sources.get(source_key, {}) if isinstance(raw_sources, dict) else {}
        ids = {
            key.split(":", 1)[1]
            for key in seen_keys
            if key.startswith(f"{source_key}:")
        }
        if isinstance(previous, dict) and isinstance(previous.get("seen_ids"), list):
            ids.update(str(item) for item in previous["seen_ids"])
        sources[source_key] = {
            "prefix": meta["prefix"],
            "seen_ids": sorted(ids, key=str),
            "total_visible": int(previous.get("total_visible") or len(ids))
            if isinstance(previous, dict)
            else len(ids),
            "total_unique_visible": int(previous.get("total_unique_visible") or len(ids))
            if isinstance(previous, dict)
            else len(ids),
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
    normalized_previous = normalize_memory_payload(previous_memory or {})
    sources = normalized_previous["sources"]
    assignments_by_source: dict[str, set[str]] = {key: set() for key in SOURCE_REGISTRY}
    for assignment in assignments:
        if assignment.platform in assignments_by_source:
            assignments_by_source[assignment.platform].add(assignment.source_id)

    for result in platform_results:
        if result.status != "ok" or result.platform not in sources:
            continue
        ids = sorted(assignments_by_source.get(result.platform, set()), key=str)
        sources[result.platform] = {
            "prefix": SOURCE_REGISTRY[result.platform]["prefix"],
            "seen_ids": ids,
            "total_visible": result.count,
            "total_unique_visible": len(ids),
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
