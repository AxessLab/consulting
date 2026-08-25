"""Persistent dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import AssignmentRecord, PlatformScanResult

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEMORY_PATH = REPO_ROOT / "assignment-listing-seen.json"
SOURCE_REGISTRY: dict[str, str] = {
    "verama.com": "v",
    "chaspartnernetwork.se": "c",
    "allakonsultuppdrag.se": "a",
}


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


def seen_ids_by_source(data: dict[str, Any]) -> dict[str, set[str]]:
    grouped: dict[str, set[str]] = {source: set() for source in SOURCE_REGISTRY}
    for key in collect_seen_keys(data):
        if ":" not in key:
            continue
        source_key, source_id = key.split(":", 1)
        grouped.setdefault(source_key, set()).add(source_id)
    return grouped


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize to the unified per-source memory shape used by cloud runs."""
    grouped = seen_ids_by_source(payload)
    raw_sources = payload.get("sources") if isinstance(payload.get("sources"), dict) else {}
    normalized_sources: dict[str, Any] = {}

    for source_key, prefix in SOURCE_REGISTRY.items():
        raw_state = raw_sources.get(source_key) if isinstance(raw_sources, dict) else None
        raw_state = raw_state if isinstance(raw_state, dict) else {}
        seen_ids = sorted(grouped.get(source_key, set()), key=str)
        normalized_sources[source_key] = {
            "prefix": raw_state.get("prefix") or prefix,
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


def build_memory_payload(
    *,
    assignments: list[AssignmentRecord],
    platform_results: list[PlatformScanResult],
    scan_date: date,
    previous_memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    previous_memory = normalize_memory_payload(previous_memory or {})
    previous_sources = previous_memory.get("sources", {})
    sources: dict[str, Any] = {}
    by_source: dict[str, dict[str, AssignmentRecord]] = {}
    for assignment in assignments:
        by_source.setdefault(assignment.platform, {})[assignment.source_id] = assignment

    for result in platform_results:
        prefix = SOURCE_REGISTRY.get(result.platform)
        if prefix is None:
            continue
        if result.status != "ok":
            previous = previous_sources.get(result.platform)
            if isinstance(previous, dict):
                sources[result.platform] = previous
            else:
                sources[result.platform] = {
                    "prefix": prefix,
                    "seen_ids": [],
                    "total_visible": 0,
                    "total_unique_visible": 0,
                }
            continue

        unique_ids = sorted(by_source.get(result.platform, {}).keys(), key=str)
        sources[result.platform] = {
            "prefix": prefix,
            "seen_ids": unique_ids,
            "total_visible": result.count,
            "total_unique_visible": len(unique_ids),
        }

    for source_key, prefix in SOURCE_REGISTRY.items():
        sources.setdefault(
            source_key,
            previous_sources.get(
                source_key,
                {
                    "prefix": prefix,
                    "seen_ids": [],
                    "total_visible": 0,
                    "total_unique_visible": 0,
                },
            ),
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
