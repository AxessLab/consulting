"""Persistent per-source dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import AssignmentRecord, PREFIX_BY_SOURCE, SOURCE_ORDER, PlatformScanResult

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEMORY_PATH = REPO_ROOT / "assignment-listing-seen.json"


def empty_memory() -> dict[str, Any]:
    return {
        "last_scan_at": None,
        "scan_date": None,
        "sources": {
            source: {
                "prefix": PREFIX_BY_SOURCE[source],
                "seen_ids": [],
                "total_visible": 0,
                "total_unique_visible": 0,
            }
            for source in SOURCE_ORDER
        },
    }


def source_seen_ids(data: dict[str, Any]) -> dict[str, set[str]]:
    """Read bare source ids from the unified shape, falling back to legacy shapes."""
    seen_by_source: dict[str, set[str]] = {source: set() for source in SOURCE_ORDER}
    sources = data.get("sources")
    if isinstance(sources, dict):
        for source, state in sources.items():
            if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
                seen_by_source.setdefault(source, set()).update(str(item) for item in state["seen_ids"])

    for key in collect_seen_keys(data):
        if ":" not in key:
            continue
        source, source_id = key.split(":", 1)
        seen_by_source.setdefault(source, set()).add(source_id)

    return seen_by_source


def collect_seen_keys(data: dict[str, Any]) -> set[str]:
    """Read seen dedupe keys from current or legacy memory shapes."""
    seen_keys: set[str] = set()
    sources = data.get("sources")
    if isinstance(sources, dict):
        for source, state in sources.items():
            if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
                for source_id in state["seen_ids"]:
                    seen_keys.add(f"{source}:{source_id}")

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
    """Normalize current and legacy payloads into the unified `sources` shape."""
    normalized = empty_memory()
    normalized["last_scan_at"] = payload.get("last_scan_at")
    normalized["scan_date"] = payload.get("scan_date")

    raw_sources = payload.get("sources")
    if isinstance(raw_sources, dict):
        for source, state in raw_sources.items():
            if not isinstance(state, dict):
                continue
            prefix = state.get("prefix") or PREFIX_BY_SOURCE.get(source, "")
            seen_ids = state.get("seen_ids") if isinstance(state.get("seen_ids"), list) else []
            normalized["sources"][source] = {
                "prefix": prefix,
                "seen_ids": sorted({str(item) for item in seen_ids}),
                "total_visible": int(state.get("total_visible") or len(seen_ids)),
                "total_unique_visible": int(state.get("total_unique_visible") or len(set(seen_ids))),
            }

    for source, ids in source_seen_ids(payload).items():
        if source not in normalized["sources"]:
            normalized["sources"][source] = {
                "prefix": PREFIX_BY_SOURCE.get(source, ""),
                "seen_ids": [],
                "total_visible": 0,
                "total_unique_visible": 0,
            }
        if ids and not normalized["sources"][source]["seen_ids"]:
            sorted_ids = sorted(str(item) for item in ids)
            normalized["sources"][source]["seen_ids"] = sorted_ids
            normalized["sources"][source]["total_visible"] = len(sorted_ids)
            normalized["sources"][source]["total_unique_visible"] = len(sorted_ids)

    return normalized


def load_memory(path: Path) -> tuple[set[str], dict[str, Any]]:
    if not path.is_file() or path.stat().st_size == 0:
        data = empty_memory()
        return set(), data
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        data = empty_memory()
        return set(), data

    normalized = normalize_memory_payload(data)
    return collect_seen_keys(normalized), normalized


def build_memory_payload(
    *,
    assignments: list[AssignmentRecord],
    platform_results: list[PlatformScanResult],
    scan_date: date,
    previous_memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    previous = normalize_memory_payload(previous_memory or {})
    result_by_source = {result.platform: result for result in platform_results}
    records_by_source: dict[str, list[AssignmentRecord]] = {source: [] for source in SOURCE_ORDER}
    for assignment in assignments:
        records_by_source.setdefault(assignment.platform, []).append(assignment)

    sources = previous.get("sources", {})
    updated_sources: dict[str, Any] = {}
    for source in SOURCE_ORDER:
        previous_state = sources.get(
            source,
            {
                "prefix": PREFIX_BY_SOURCE.get(source, ""),
                "seen_ids": [],
                "total_visible": 0,
                "total_unique_visible": 0,
            },
        )
        result = result_by_source.get(source)
        if result and result.status == "ok":
            ids = sorted({record.source_id for record in records_by_source.get(source, [])})
            updated_sources[source] = {
                "prefix": PREFIX_BY_SOURCE[source],
                "seen_ids": ids,
                "total_visible": result.count,
                "total_unique_visible": len(ids),
            }
        else:
            updated_sources[source] = previous_state

    for result in platform_results:
        if result.platform not in updated_sources:
            updated_sources[result.platform] = {
                "prefix": PREFIX_BY_SOURCE.get(result.platform, ""),
                "seen_ids": [],
                "total_visible": result.count if result.status == "ok" else 0,
                "total_unique_visible": 0,
            }

    return {
        "last_scan_at": now,
        "scan_date": scan_date.isoformat(),
        "sources": updated_sources,
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
