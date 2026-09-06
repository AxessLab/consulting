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


def seen_ids_by_source(data: dict[str, Any]) -> dict[str, set[str]]:
    """Return bare native IDs grouped by source key."""
    grouped = {source_key: set() for source_key in DEFAULT_PLATFORMS}
    for dedupe_key in collect_seen_keys(data):
        source_key, _, source_id = dedupe_key.partition(":")
        if source_key and source_id:
            grouped.setdefault(source_key, set()).add(source_id)
    return grouped


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize current and legacy memory into the unified per-source shape."""
    sources: dict[str, Any] = {}
    raw_sources = payload.get("sources")
    if isinstance(raw_sources, dict):
        for source_key, state in raw_sources.items():
            if not isinstance(state, dict):
                continue
            seen_ids = state.get("seen_ids") if isinstance(state.get("seen_ids"), list) else []
            sources[source_key] = {
                "prefix": str(state.get("prefix") or SOURCE_PREFIXES.get(source_key, "")),
                "seen_ids": sorted({str(item) for item in seen_ids}),
                "total_visible": int(state.get("total_visible") or 0),
                "total_unique_visible": int(state.get("total_unique_visible") or 0),
            }

    for source_key, source_ids in seen_ids_by_source(payload).items():
        entry = sources.setdefault(
            source_key,
            {
                "prefix": SOURCE_PREFIXES.get(source_key, ""),
                "seen_ids": [],
                "total_visible": 0,
                "total_unique_visible": 0,
            },
        )
        entry["seen_ids"] = sorted(set(entry["seen_ids"]) | source_ids)

    for source_key in DEFAULT_PLATFORMS:
        sources.setdefault(
            source_key,
            {
                "prefix": SOURCE_PREFIXES.get(source_key, ""),
                "seen_ids": [],
                "total_visible": 0,
                "total_unique_visible": 0,
            },
        )

    normalized: dict[str, Any] = {
        "source": payload.get("source", "multi-platform assignment listing"),
        "last_scan_at": payload.get("last_scan_at"),
        "scan_date": payload.get("scan_date"),
        "sources": sources,
        "total_visible": payload.get(
            "total_visible",
            sum(len(source["seen_ids"]) for source in sources.values()),
        ),
        "total_unique_visible": payload.get(
            "total_unique_visible",
            sum(len(source["seen_ids"]) for source in sources.values()),
        ),
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
        source_key: dict(state)
        for source_key, state in (previous.get("sources") or {}).items()
        if isinstance(state, dict)
    }

    ids_by_source: dict[str, set[str]] = {}
    for assignment in assignments:
        ids_by_source.setdefault(assignment.platform, set()).add(str(assignment.source_id))

    for result in platform_results:
        sources.setdefault(
            result.platform,
            {
                "prefix": SOURCE_PREFIXES.get(result.platform, ""),
                "seen_ids": [],
                "total_visible": 0,
                "total_unique_visible": 0,
            },
        )
        if result.status != "ok":
            continue
        source_ids = sorted(ids_by_source.get(result.platform, set()))
        sources[result.platform] = {
            "prefix": SOURCE_PREFIXES.get(result.platform, ""),
            "seen_ids": source_ids,
            "total_visible": result.count,
            "total_unique_visible": len(source_ids),
        }

    return {
        "source": "multi-platform assignment listing",
        "last_scan_at": now,
        "scan_date": scan_date.isoformat(),
        "sources": sources,
        "total_visible": sum(
            state["total_visible"] for state in sources.values() if isinstance(state, dict)
        ),
        "total_unique_visible": sum(
            state["total_unique_visible"]
            for state in sources.values()
            if isinstance(state, dict)
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
