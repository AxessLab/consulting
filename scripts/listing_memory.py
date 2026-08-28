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
    """Read seen dedupe keys from current per-source or legacy memory shapes."""
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
    seen: dict[str, set[str]] = {}
    for dedupe_key in collect_seen_keys(data):
        if ":" not in dedupe_key:
            continue
        source_key, source_id = dedupe_key.split(":", 1)
        seen.setdefault(source_key, set()).add(source_id)
    return seen


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize memory to the unified per-source seen-id shape."""
    sources: dict[str, dict[str, Any]] = {
        source_key: {
            "prefix": source_prefix(source_key),
            "seen_ids": [],
            "total_visible": 0,
            "total_unique_visible": 0,
        }
        for source_key in SOURCE_REGISTRY
    }

    raw_sources = payload.get("sources")
    if isinstance(raw_sources, dict):
        for source_key, state in raw_sources.items():
            if not isinstance(state, dict):
                continue
            seen_ids = state.get("seen_ids") if isinstance(state.get("seen_ids"), list) else []
            sources[source_key] = {
                "prefix": str(state.get("prefix") or source_prefix(source_key)),
                "seen_ids": sorted({str(item) for item in seen_ids}),
                "total_visible": int(state.get("total_visible") or len(seen_ids)),
                "total_unique_visible": int(state.get("total_unique_visible") or len(set(seen_ids))),
            }

    for dedupe_key in collect_seen_keys(payload):
        if ":" not in dedupe_key:
            continue
        source_key, source_id = dedupe_key.split(":", 1)
        entry = sources.setdefault(
            source_key,
            {
                "prefix": source_prefix(source_key),
                "seen_ids": [],
                "total_visible": 0,
                "total_unique_visible": 0,
            },
        )
        entry["seen_ids"] = sorted({*entry.get("seen_ids", []), source_id})
        entry["total_unique_visible"] = max(
            int(entry.get("total_unique_visible") or 0),
            len(entry["seen_ids"]),
        )
        entry["total_visible"] = max(
            int(entry.get("total_visible") or 0),
            int(entry.get("total_unique_visible") or 0),
        )

    raw_platforms = payload.get("platforms")
    if isinstance(raw_platforms, dict):
        for platform_id, state in raw_platforms.items():
            if not isinstance(state, dict):
                continue
            if isinstance(state.get("seen_ids"), list):
                seen_ids = sorted({str(item) for item in state["seen_ids"]})
                sources[platform_id] = {
                    "prefix": source_prefix(platform_id),
                    "seen_ids": seen_ids,
                    "total_visible": int(state.get("total_visible") or len(seen_ids)),
                    "total_unique_visible": int(
                        state.get("total_unique_visible") or len(seen_ids)
                    ),
                }

    normalized: dict[str, Any] = {
        "source": payload.get("source", "multi-platform assignment listing"),
        "last_scan_at": payload.get("last_scan_at"),
        "scan_date": payload.get("scan_date"),
        "sources": sources,
        "total_visible": payload.get(
            "total_visible",
            sum(int(item.get("total_visible") or 0) for item in sources.values()),
        ),
        "total_unique_visible": payload.get(
            "total_unique_visible",
            sum(int(item.get("total_unique_visible") or 0) for item in sources.values()),
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
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    successful_sources = {result.platform for result in platform_results if result.status == "ok"}
    visible_ids_by_source: dict[str, set[str]] = {
        source_key: set() for source_key in successful_sources
    }
    for assignment in assignments:
        source_key = assignment.resolved_source_key
        if source_key in successful_sources:
            visible_ids_by_source.setdefault(source_key, set()).add(assignment.source_id)

    sources: dict[str, Any] = {}
    for result in platform_results:
        if result.status != "ok":
            continue
        seen_ids = sorted(visible_ids_by_source.get(result.platform, set()))
        sources[result.platform] = {
            "prefix": source_prefix(result.platform),
            "seen_ids": seen_ids,
            "total_visible": result.count,
            "total_unique_visible": len(seen_ids),
        }

    return {
        "source": "multi-platform assignment listing",
        "last_scan_at": now,
        "scan_date": scan_date.isoformat(),
        "sources": sources,
        "total_visible": sum(result.count for result in platform_results if result.status == "ok"),
        "total_unique_visible": sum(
            len(visible_ids_by_source.get(result.platform, set()))
            for result in platform_results
            if result.status == "ok"
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
    _, existing = load_memory(memory_path)
    merged = normalize_memory_payload(existing)
    update = normalize_memory_payload(memory_update)
    for source_key, state in update.get("sources", {}).items():
        if source_key in memory_update.get("sources", {}):
            merged["sources"][source_key] = state
    merged["source"] = update.get("source", merged.get("source"))
    merged["last_scan_at"] = update.get("last_scan_at", merged.get("last_scan_at"))
    merged["scan_date"] = update.get("scan_date", merged.get("scan_date"))
    merged["total_visible"] = sum(
        int(item.get("total_visible") or 0) for item in merged["sources"].values()
    )
    merged["total_unique_visible"] = sum(
        int(item.get("total_unique_visible") or 0) for item in merged["sources"].values()
    )
    write_memory_file(memory_path, merged)


def read_memory_export(memory_path: Path) -> str:
    if not memory_path.is_file() or memory_path.stat().st_size == 0:
        return ""
    return memory_path.read_text(encoding="utf-8")
