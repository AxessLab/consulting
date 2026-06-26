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
        source_key: {
            "prefix": config.prefix,
            "seen_ids": [],
            "total_visible": 0,
            "total_unique_visible": 0,
        }
        for source_key, config in SOURCE_REGISTRY.items()
        if config.active
    }


def _dedupe_id_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return sorted({str(value) for value in values if value not in (None, "")})


def collect_seen_keys(data: dict[str, Any]) -> set[str]:
    """Read seen dedupe keys from current and legacy memory shapes."""
    seen_keys: set[str] = set()

    sources = data.get("sources")
    if isinstance(sources, dict):
        for source_key, state in sources.items():
            if isinstance(state, dict):
                for source_id in _dedupe_id_list(state.get("seen_ids")):
                    seen_keys.add(f"{source_key}:{source_id}")

    if isinstance(data.get("seen_keys"), list):
        seen_keys.update(str(item) for item in data["seen_keys"])

    legacy_platforms = data.get("platforms")
    if isinstance(legacy_platforms, dict):
        for source_key, state in legacy_platforms.items():
            if isinstance(state, dict):
                for source_id in _dedupe_id_list(state.get("seen_ids")):
                    seen_keys.add(f"{source_key}:{source_id}")

    legacy_seen = data.get("seen_ids")
    if isinstance(legacy_seen, list):
        for source_id in legacy_seen:
            seen_keys.add(f"allakonsultuppdrag.se:{source_id}")

    return seen_keys


def collect_seen_ids_by_source(data: dict[str, Any]) -> dict[str, set[str]]:
    seen: dict[str, set[str]] = {source_key: set() for source_key in SOURCE_REGISTRY}
    for key in collect_seen_keys(data):
        source_key, _, source_id = key.partition(":")
        if source_key and source_id:
            seen.setdefault(source_key, set()).add(source_id)
    return seen


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize memory to the unified per-source shape."""
    sources = _default_sources()
    raw_sources = payload.get("sources")
    if isinstance(raw_sources, dict):
        for source_key, state in raw_sources.items():
            if not isinstance(state, dict):
                continue
            config = SOURCE_REGISTRY.get(source_key)
            sources[source_key] = {
                "prefix": state.get("prefix") or (config.prefix if config else ""),
                "seen_ids": _dedupe_id_list(state.get("seen_ids")),
                "total_visible": int(state.get("total_visible") or 0),
                "total_unique_visible": int(state.get("total_unique_visible") or 0),
            }

    for source_key, ids in collect_seen_ids_by_source(payload).items():
        if not ids:
            continue
        config = SOURCE_REGISTRY.get(source_key)
        existing = sources.setdefault(
            source_key,
            {
                "prefix": config.prefix if config else "",
                "seen_ids": [],
                "total_visible": 0,
                "total_unique_visible": 0,
            },
        )
        merged = set(existing.get("seen_ids") or [])
        merged.update(ids)
        existing["seen_ids"] = sorted(merged)
        if not existing.get("total_visible"):
            existing["total_visible"] = len(existing["seen_ids"])
        if not existing.get("total_unique_visible"):
            existing["total_unique_visible"] = len(existing["seen_ids"])

    return {
        "last_scan_at": payload.get("last_scan_at"),
        "scan_date": payload.get("scan_date"),
        "sources": sources,
    }


def load_memory(path: Path) -> tuple[set[str], dict[str, Any]]:
    if not path.is_file() or path.stat().st_size == 0:
        return set(), normalize_memory_payload({})
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set(), normalize_memory_payload({})

    normalized = normalize_memory_payload(data if isinstance(data, dict) else {})
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
    payload["last_scan_at"] = now
    payload["scan_date"] = scan_date.isoformat()

    source_ids_by_source: dict[str, set[str]] = {}
    for assignment in assignments:
        source_ids_by_source.setdefault(assignment.source_key, set()).add(assignment.source_id)

    for result in platform_results:
        if result.status != "ok":
            continue
        config = SOURCE_REGISTRY.get(result.platform)
        ids = sorted(source_ids_by_source.get(result.platform, set()))
        payload["sources"][result.platform] = {
            "prefix": config.prefix if config else "",
            "seen_ids": ids,
            "total_visible": result.count,
            "total_unique_visible": len(ids),
        }

    return normalize_memory_payload(payload)


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
