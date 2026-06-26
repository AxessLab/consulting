"""Persistent per-source dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import AssignmentRecord, PlatformScanResult, SOURCE_REGISTRY

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEMORY_PATH = REPO_ROOT / "assignment-listing-seen.json"


def _default_sources() -> dict[str, dict[str, Any]]:
    return {
        source.source_key: {
            "prefix": source.prefix,
            "seen_ids": [],
            "total_visible": 0,
            "total_unique_visible": 0,
        }
        for source in SOURCE_REGISTRY
        if source.active
    }


def collect_seen_sources(data: dict[str, Any]) -> dict[str, set[str]]:
    """Read bare per-source ids from current or legacy memory shapes."""
    seen: dict[str, set[str]] = {key: set() for key in _default_sources()}

    sources = data.get("sources")
    if isinstance(sources, dict):
        for source_key, state in sources.items():
            if not isinstance(state, dict) or not isinstance(state.get("seen_ids"), list):
                continue
            seen.setdefault(source_key, set()).update(str(item) for item in state["seen_ids"])

    legacy_seen_keys = data.get("seen_keys")
    if isinstance(legacy_seen_keys, list):
        for item in legacy_seen_keys:
            if not isinstance(item, str) or ":" not in item:
                continue
            source_key, source_id = item.split(":", 1)
            seen.setdefault(source_key, set()).add(source_id)

    legacy_platforms = data.get("platforms")
    if isinstance(legacy_platforms, dict):
        for source_key, state in legacy_platforms.items():
            if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
                seen.setdefault(source_key, set()).update(
                    str(source_id) for source_id in state["seen_ids"]
                )

    legacy_allakonsult = data.get("seen_ids")
    if isinstance(legacy_allakonsult, list):
        seen.setdefault("allakonsultuppdrag.se", set()).update(
            str(source_id) for source_id in legacy_allakonsult
        )

    return seen


def collect_seen_keys(data: dict[str, Any]) -> set[str]:
    return {
        f"{source_key}:{source_id}"
        for source_key, ids in collect_seen_sources(data).items()
        for source_id in ids
    }


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize current and legacy payloads into the unified sources shape."""
    seen_sources = collect_seen_sources(payload)
    sources = _default_sources()
    raw_sources = payload.get("sources") if isinstance(payload.get("sources"), dict) else {}

    for source_key, ids in seen_sources.items():
        registry_entry = next(
            (source for source in SOURCE_REGISTRY if source.source_key == source_key),
            None,
        )
        entry = sources.setdefault(
            source_key,
            {
                "prefix": registry_entry.prefix if registry_entry else "",
                "seen_ids": [],
                "total_visible": 0,
                "total_unique_visible": 0,
            },
        )
        raw_entry = raw_sources.get(source_key) if isinstance(raw_sources, dict) else None
        if isinstance(raw_entry, dict):
            entry["prefix"] = raw_entry.get("prefix") or entry["prefix"]
            entry["total_visible"] = int(raw_entry.get("total_visible") or 0)
            entry["total_unique_visible"] = int(raw_entry.get("total_unique_visible") or 0)
        entry["seen_ids"] = sorted(ids)

    normalized: dict[str, Any] = {
        "last_scan_at": payload.get("last_scan_at"),
        "scan_date": payload.get("scan_date"),
        "sources": sources,
    }
    return normalized


def load_memory(path: Path) -> tuple[set[str], dict[str, Any]]:
    if not path.is_file() or path.stat().st_size == 0:
        return set(), normalize_memory_payload({})
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set(), normalize_memory_payload({})

    normalized = normalize_memory_payload(data) if isinstance(data, dict) else normalize_memory_payload({})
    return collect_seen_keys(normalized), normalized


def build_memory_payload(
    *,
    assignments: list[AssignmentRecord],
    platform_results: list[PlatformScanResult],
    scan_date: date,
    previous_memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    payload = normalize_memory_payload(previous_memory or {})
    sources = payload["sources"]

    for result in platform_results:
        if result.status != "ok":
            continue
        source_records = [
            assignment for assignment in assignments if assignment.source_key == result.source_key
        ]
        unique_ids = sorted({assignment.source_id for assignment in source_records})
        registry_entry = next(
            (source for source in SOURCE_REGISTRY if source.source_key == result.source_key),
            None,
        )
        sources[result.source_key] = {
            "prefix": registry_entry.prefix if registry_entry else "",
            "seen_ids": unique_ids,
            "total_visible": result.count,
            "total_unique_visible": len(unique_ids),
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
