"""Persistent dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import AssignmentRecord, PlatformScanResult, SOURCE_REGISTRY, source_prefix

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


def _source_state_from_assignments(
    source_key: str,
    assignments: list[AssignmentRecord],
    result: PlatformScanResult | None,
) -> dict[str, Any]:
    source_ids = sorted(
        {assignment.source_id for assignment in assignments if assignment.platform == source_key},
        key=lambda value: (len(value), value),
    )
    return {
        "prefix": source_prefix(source_key),
        "seen_ids": source_ids,
        "total_visible": result.count if result else len(source_ids),
        "total_unique_visible": len(source_ids),
    }


def _legacy_sources_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sources = payload.get("sources")
    if isinstance(sources, dict):
        return {
            source_key: state
            for source_key, state in sources.items()
            if isinstance(state, dict)
        }

    migrated: dict[str, Any] = {}
    for seen_key in sorted(collect_seen_keys(payload)):
        if ":" not in seen_key:
            continue
        source_key, source_id = seen_key.split(":", 1)
        entry = migrated.setdefault(
            source_key,
            {
                "prefix": source_prefix(source_key),
                "seen_ids": [],
                "total_visible": 0,
                "total_unique_visible": 0,
            },
        )
        entry["seen_ids"].append(source_id)
    for entry in migrated.values():
        entry["seen_ids"] = sorted(set(entry["seen_ids"]), key=lambda value: (len(value), value))
        entry["total_visible"] = len(entry["seen_ids"])
        entry["total_unique_visible"] = len(entry["seen_ids"])
    return migrated


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize to the current per-source dedupe memory shape."""
    sources = _legacy_sources_from_payload(payload)
    for source_key, registry_entry in SOURCE_REGISTRY.items():
        sources.setdefault(
            source_key,
            {
                "prefix": registry_entry["prefix"],
                "seen_ids": [],
                "total_visible": 0,
                "total_unique_visible": 0,
            },
        )
        sources[source_key]["prefix"] = registry_entry["prefix"]
        seen_ids = sources[source_key].get("seen_ids")
        if not isinstance(seen_ids, list):
            seen_ids = []
        normalized_ids = sorted({str(item) for item in seen_ids}, key=lambda value: (len(value), value))
        sources[source_key]["seen_ids"] = normalized_ids
        sources[source_key]["total_visible"] = int(sources[source_key].get("total_visible") or len(normalized_ids))
        sources[source_key]["total_unique_visible"] = int(
            sources[source_key].get("total_unique_visible") or len(normalized_ids)
        )

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
    existing_memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    existing_sources = normalize_memory_payload(existing_memory or {}).get("sources", {})
    results_by_platform = {result.platform: result for result in platform_results}
    sources: dict[str, Any] = dict(existing_sources)
    for result in platform_results:
        if result.status != "ok":
            continue
        sources[result.platform] = _source_state_from_assignments(
            result.platform,
            assignments,
            results_by_platform.get(result.platform),
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
