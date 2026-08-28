"""Persistent dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import AssignmentRecord, DEFAULT_PLATFORMS, PlatformScanResult

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEMORY_PATH = REPO_ROOT / "assignment-listing-seen.json"
SOURCE_PREFIXES = {
    "allakonsultuppdrag.se": "a",
    "verama.com": "v",
    "chaspartnernetwork.se": "c",
    "magnit-source.magnitglobal.com": "m",
    "cinode.com/market": "n",
}


def _source_prefix(platform_id: str) -> str:
    return SOURCE_PREFIXES.get(platform_id, "")


def _empty_source_state(platform_id: str) -> dict[str, Any]:
    return {
        "prefix": _source_prefix(platform_id),
        "seen_ids": [],
        "total_visible": 0,
        "total_unique_visible": 0,
    }


def _source_seen_ids(data: dict[str, Any]) -> dict[str, set[str]]:
    """Read bare source ids from current and legacy memory shapes."""
    by_source: dict[str, set[str]] = {}

    sources = data.get("sources")
    if isinstance(sources, dict):
        for platform_id, state in sources.items():
            if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
                by_source.setdefault(platform_id, set()).update(
                    str(item) for item in state["seen_ids"]
                )

    platforms = data.get("platforms")
    if isinstance(platforms, dict):
        for platform_id, state in platforms.items():
            if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
                by_source.setdefault(platform_id, set()).update(
                    str(item) for item in state["seen_ids"]
                )

    if isinstance(data.get("seen_keys"), list):
        for key in data["seen_keys"]:
            platform_id, sep, source_id = str(key).partition(":")
            if sep and source_id:
                by_source.setdefault(platform_id, set()).add(source_id)

    legacy_seen = data.get("seen_ids")
    if isinstance(legacy_seen, list):
        by_source.setdefault("allakonsultuppdrag.se", set()).update(
            str(item) for item in legacy_seen
        )

    return by_source


def collect_seen_keys(data: dict[str, Any]) -> set[str]:
    """Read seen dedupe keys from current or legacy memory shapes."""
    seen_keys: set[str] = set()
    for platform_id, source_ids in _source_seen_ids(data).items():
        for source_id in source_ids:
            seen_keys.add(f"{platform_id}:{source_id}")

    if isinstance(data.get("seen_keys"), list):
        seen_keys.update(str(item) for item in data["seen_keys"])

    return seen_keys


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize all supported memory shapes into the per-source schema."""
    seen_by_source = _source_seen_ids(payload)
    raw_sources = payload.get("sources")
    raw_platforms = payload.get("platforms")
    sources: dict[str, Any] = {
        platform_id: _empty_source_state(platform_id) for platform_id in DEFAULT_PLATFORMS
    }

    raw_source_items = (
        (raw_sources or {}).items() if isinstance(raw_sources, dict) else []
    )
    for platform_id, state in raw_source_items:
        if not isinstance(state, dict):
            continue
        entry = sources.setdefault(platform_id, _empty_source_state(platform_id))
        entry["prefix"] = str(state.get("prefix") or entry.get("prefix") or "")
        entry["total_visible"] = int(state.get("total_visible") or 0)
        entry["total_unique_visible"] = int(state.get("total_unique_visible") or 0)

    raw_platform_items = (
        (raw_platforms or {}).items() if isinstance(raw_platforms, dict) else []
    )
    for platform_id, state in raw_platform_items:
        if not isinstance(state, dict):
            continue
        entry = sources.setdefault(platform_id, _empty_source_state(platform_id))
        entry["total_visible"] = int(
            state.get("total_visible") or entry.get("total_visible") or 0
        )
        entry["total_unique_visible"] = int(
            state.get("total_unique_visible") or entry.get("total_unique_visible") or 0
        )

    for platform_id, seen_ids in seen_by_source.items():
        entry = sources.setdefault(platform_id, _empty_source_state(platform_id))
        entry["seen_ids"] = sorted(seen_ids)
        if not entry.get("total_unique_visible"):
            entry["total_unique_visible"] = len(seen_ids)
        if not entry.get("total_visible"):
            entry["total_visible"] = len(seen_ids)

    total_visible = sum(int(state.get("total_visible") or 0) for state in sources.values())
    total_unique_visible = sum(
        int(state.get("total_unique_visible") or 0) for state in sources.values()
    )

    normalized: dict[str, Any] = {
        "source": payload.get("source", "multi-platform assignment listing"),
        "last_scan_at": payload.get("last_scan_at"),
        "scan_date": payload.get("scan_date"),
        "sources": sources,
        "total_visible": payload.get("total_visible", total_visible),
        "total_unique_visible": payload.get("total_unique_visible", total_unique_visible),
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
    previous = normalize_memory_payload(previous_memory or {})
    sources: dict[str, Any] = {
        platform_id: dict(state)
        for platform_id, state in (previous.get("sources") or {}).items()
        if isinstance(state, dict)
    }

    ids_by_platform: dict[str, set[str]] = {}
    for assignment in assignments:
        ids_by_platform.setdefault(assignment.platform, set()).add(assignment.source_id)

    for result in platform_results:
        if result.status != "ok":
            continue
        source_ids = ids_by_platform.get(result.platform, set())
        sources[result.platform] = {
            "prefix": _source_prefix(result.platform),
            "seen_ids": sorted(source_ids),
            "total_visible": result.count,
            "total_unique_visible": len(source_ids),
        }

    return {
        "source": "multi-platform assignment listing",
        "last_scan_at": now,
        "scan_date": scan_date.isoformat(),
        "sources": sources,
        "total_visible": sum(
            int(state.get("total_visible") or 0) for state in sources.values()
        ),
        "total_unique_visible": sum(
            int(state.get("total_unique_visible") or 0) for state in sources.values()
        ),
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
