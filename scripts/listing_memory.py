"""Persistent dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import AssignmentRecord, PlatformScanResult, SOURCE_PREFIXES

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEMORY_PATH = REPO_ROOT / "assignment-listing-seen.json"


def _default_source_state(source_key: str) -> dict[str, Any]:
    return {
        "prefix": SOURCE_PREFIXES[source_key],
        "seen_ids": [],
        "total_visible": 0,
        "total_unique_visible": 0,
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


def collect_seen_ids_by_source(data: dict[str, Any]) -> dict[str, set[str]]:
    by_source = {source: set() for source in SOURCE_PREFIXES}
    for seen_key in collect_seen_keys(data):
        if ":" not in seen_key:
            continue
        source_key, source_id = seen_key.split(":", 1)
        by_source.setdefault(source_key, set()).add(str(source_id))
    return by_source


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize current and legacy memory into the unified per-source shape."""
    seen_by_source = collect_seen_ids_by_source(payload)
    sources: dict[str, Any] = {
        source_key: _default_source_state(source_key) for source_key in SOURCE_PREFIXES
    }

    raw_sources = payload.get("sources")
    if isinstance(raw_sources, dict):
        for source_key, state in raw_sources.items():
            if source_key not in SOURCE_PREFIXES or not isinstance(state, dict):
                continue
            seen_ids = state.get("seen_ids")
            if isinstance(seen_ids, list):
                seen_by_source[source_key] = {str(item) for item in seen_ids}
            sources[source_key] = {
                "prefix": state.get("prefix") or SOURCE_PREFIXES[source_key],
                "seen_ids": sorted(seen_by_source.get(source_key, set()), key=str),
                "total_visible": int(state.get("total_visible") or 0),
                "total_unique_visible": int(state.get("total_unique_visible") or 0),
            }

    raw_platforms = payload.get("platforms")
    if isinstance(raw_platforms, dict):
        for source_key, state in raw_platforms.items():
            if source_key not in SOURCE_PREFIXES or not isinstance(state, dict):
                continue
            sources[source_key]["seen_ids"] = sorted(
                seen_by_source.get(source_key, set()), key=str
            )
            if state.get("total_visible") is not None:
                sources[source_key]["total_visible"] = int(state.get("total_visible") or 0)
                sources[source_key]["total_unique_visible"] = int(
                    state.get("total_unique_visible")
                    or state.get("total_visible")
                    or len(sources[source_key]["seen_ids"])
                )

    for source_key in SOURCE_PREFIXES:
        sources[source_key]["prefix"] = SOURCE_PREFIXES[source_key]
        sources[source_key]["seen_ids"] = sorted(
            {str(item) for item in sources[source_key].get("seen_ids", [])}, key=str
        )

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
    existing_memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    normalized_existing = normalize_memory_payload(existing_memory or {})
    sources = normalized_existing["sources"]
    ids_by_source: dict[str, set[str]] = {source: set() for source in SOURCE_PREFIXES}
    for assignment in assignments:
        ids_by_source.setdefault(assignment.platform, set()).add(str(assignment.source_id))

    for result in platform_results:
        if result.platform not in SOURCE_PREFIXES or result.status != "ok":
            continue
        seen_ids = sorted(ids_by_source.get(result.platform, set()), key=str)
        sources[result.platform] = {
            "prefix": SOURCE_PREFIXES[result.platform],
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
