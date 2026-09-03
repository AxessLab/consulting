"""Persistent dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import AssignmentRecord, PLATFORM_PREFIXES, PlatformScanResult

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


def _source_states_from_payload(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sources = {
        source_key: {
            "prefix": prefix,
            "seen_ids": [],
            "total_visible": 0,
            "total_unique_visible": 0,
        }
        for source_key, prefix in PLATFORM_PREFIXES.items()
    }

    raw_sources = payload.get("sources")
    if isinstance(raw_sources, dict):
        for source_key, state in raw_sources.items():
            if source_key not in sources or not isinstance(state, dict):
                continue
            seen_ids = [str(item) for item in state.get("seen_ids", [])]
            sources[source_key] = {
                "prefix": state.get("prefix") or PLATFORM_PREFIXES[source_key],
                "seen_ids": sorted(set(seen_ids)),
                "total_visible": int(state.get("total_visible") or len(set(seen_ids))),
                "total_unique_visible": int(
                    state.get("total_unique_visible") or len(set(seen_ids))
                ),
            }

    for dedupe_key in collect_seen_keys(payload):
        if ":" not in dedupe_key:
            continue
        source_key, source_id = dedupe_key.split(":", 1)
        if source_key not in sources:
            continue
        current_ids = set(sources[source_key]["seen_ids"])
        current_ids.add(str(source_id))
        sources[source_key]["seen_ids"] = sorted(current_ids)
        if not sources[source_key]["total_visible"]:
            sources[source_key]["total_visible"] = len(current_ids)
        if not sources[source_key]["total_unique_visible"]:
            sources[source_key]["total_unique_visible"] = len(current_ids)

    return sources


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize current and legacy memory into the unified per-source shape."""
    sources = _source_states_from_payload(payload)

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
    previous_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    sources = _source_states_from_payload(previous_data or {})
    ids_by_source: dict[str, set[str]] = {source_key: set() for source_key in PLATFORM_PREFIXES}
    for assignment in assignments:
        if assignment.platform in ids_by_source:
            ids_by_source[assignment.platform].add(str(assignment.source_id))

    status_by_source = {result.platform: result for result in platform_results}
    for result in platform_results:
        if result.status != "ok" or result.platform not in sources:
            continue
        seen_ids = sorted(ids_by_source.get(result.platform, set()))
        sources[result.platform] = {
            "prefix": PLATFORM_PREFIXES[result.platform],
            "seen_ids": seen_ids,
            "total_visible": result.count,
            "total_unique_visible": len(seen_ids),
        }

    for source_key, prefix in PLATFORM_PREFIXES.items():
        sources.setdefault(
            source_key,
            {
                "prefix": prefix,
                "seen_ids": [],
                "total_visible": 0,
                "total_unique_visible": 0,
            },
        )
        if source_key not in status_by_source:
            sources[source_key]["prefix"] = prefix

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
