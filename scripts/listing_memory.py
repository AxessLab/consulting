"""Persistent dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import AssignmentRecord, PlatformScanResult, SOURCE_PREFIXES

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEMORY_PATH = REPO_ROOT / "assignment-listing-seen.json"


def collect_seen_keys(data: dict[str, Any]) -> set[str]:
    """Read seen dedupe keys from current or legacy memory shapes."""
    seen_keys: set[str] = set()
    if isinstance(data.get("seen_keys"), list):
        seen_keys.update(str(item) for item in data["seen_keys"])

    sources = data.get("sources")
    if isinstance(sources, dict):
        for source_key, state in sources.items():
            if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
                for source_id in state["seen_ids"]:
                    seen_keys.add(f"{source_key}:{source_id}")

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
    """Normalize legacy and current memory into the per-source `sources` shape."""
    seen_keys = collect_seen_keys(payload)
    sources: dict[str, Any] = {
        source_key: {
            "prefix": prefix,
            "seen_ids": [],
            "total_visible": 0,
            "total_unique_visible": 0,
        }
        for source_key, prefix in SOURCE_PREFIXES.items()
    }

    raw_sources = payload.get("sources")
    if isinstance(raw_sources, dict):
        for source_key, state in raw_sources.items():
            if not isinstance(state, dict):
                continue
            prefix = state.get("prefix") or SOURCE_PREFIXES.get(source_key, "")
            seen_ids = [str(item) for item in state.get("seen_ids") or []]
            sources[source_key] = {
                "prefix": prefix,
                "seen_ids": sorted(set(seen_ids), key=_natural_sort_key),
                "total_visible": int(state.get("total_visible") or len(set(seen_ids))),
                "total_unique_visible": int(
                    state.get("total_unique_visible") or len(set(seen_ids))
                ),
            }

    for key in seen_keys:
        if ":" not in key:
            continue
        source_key, source_id = key.split(":", 1)
        entry = sources.setdefault(
            source_key,
            {
                "prefix": SOURCE_PREFIXES.get(source_key, ""),
                "seen_ids": [],
                "total_visible": 0,
                "total_unique_visible": 0,
            },
        )
        entry["seen_ids"].append(source_id)

    for entry in sources.values():
        unique_seen = sorted(set(str(item) for item in entry["seen_ids"]), key=_natural_sort_key)
        entry["seen_ids"] = unique_seen
        if not entry.get("total_visible"):
            entry["total_visible"] = len(unique_seen)
        if not entry.get("total_unique_visible"):
            entry["total_unique_visible"] = len(unique_seen)

    normalized: dict[str, Any] = {
        "last_scan_at": payload.get("last_scan_at"),
        "scan_date": payload.get("scan_date"),
        "sources": sources,
    }
    return normalized


def _natural_sort_key(value: Any) -> tuple[int, str]:
    text = str(value)
    return (0, f"{int(text):020d}") if text.isdigit() else (1, text)


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
    base = normalize_memory_payload(previous_memory or {})
    sources = base.get("sources", {})
    by_source: dict[str, list[AssignmentRecord]] = {}
    for assignment in assignments:
        by_source.setdefault(assignment.platform, []).append(assignment)

    for result in platform_results:
        if result.status != "ok":
            continue
        visible = by_source.get(result.platform, [])
        seen_ids = sorted({assignment.source_id for assignment in visible}, key=_natural_sort_key)
        sources[result.platform] = {
            "prefix": SOURCE_PREFIXES.get(result.platform, ""),
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
