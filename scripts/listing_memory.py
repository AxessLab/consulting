"""Persistent dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import AssignmentRecord, PlatformScanResult

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


def _ids_from_seen_keys(seen_keys: set[str]) -> dict[str, set[str]]:
    by_source: dict[str, set[str]] = {}
    for key in seen_keys:
        if ":" not in key:
            continue
        source_key, source_id = key.split(":", 1)
        by_source.setdefault(source_key, set()).add(source_id)
    return by_source


def normalize_memory_payload(
    payload: dict[str, Any],
    *,
    include_registry_defaults: bool = True,
) -> dict[str, Any]:
    """Normalize current and legacy memory into the per-source shape."""
    seen_keys = collect_seen_keys(payload)
    ids_by_source = _ids_from_seen_keys(seen_keys)
    raw_sources = payload.get("sources")
    raw_platforms = payload.get("platforms")

    source_keys = set(ids_by_source)
    if isinstance(raw_sources, dict):
        source_keys.update(raw_sources)
    if include_registry_defaults:
        source_keys.update(SOURCE_PREFIXES)

    sources: dict[str, Any] = {}
    for source_key in sorted(
        source_keys,
        key=lambda value: list(SOURCE_PREFIXES).index(value)
        if value in SOURCE_PREFIXES
        else len(SOURCE_PREFIXES),
    ):
        state: dict[str, Any] = {}
        if isinstance(raw_sources, dict) and isinstance(raw_sources.get(source_key), dict):
            state = raw_sources[source_key]
        elif isinstance(raw_platforms, dict) and isinstance(raw_platforms.get(source_key), dict):
            state = raw_platforms[source_key]

        ids = sorted(ids_by_source.get(source_key, set()))
        sources[source_key] = {
            "prefix": str(state.get("prefix") or SOURCE_PREFIXES.get(source_key, "")),
            "seen_ids": ids,
            "total_visible": int(state.get("total_visible") or len(ids)),
            "total_unique_visible": int(state.get("total_unique_visible") or len(ids)),
        }

    if isinstance(raw_platforms, dict):
        for platform_id, state in raw_platforms.items():
            if not isinstance(state, dict):
                continue
            if platform_id in sources:
                continue
            ids = sorted(ids_by_source.get(platform_id, set()))
            sources[platform_id] = {
                "prefix": str(state.get("prefix") or SOURCE_PREFIXES.get(platform_id, "")),
                "seen_ids": ids,
                "total_visible": int(state.get("total_visible") or len(ids)),
                "total_unique_visible": int(state.get("total_unique_visible") or len(ids)),
            }

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
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    ids_by_source: dict[str, set[str]] = {}
    for assignment in assignments:
        ids_by_source.setdefault(assignment.platform, set()).add(assignment.source_id)

    sources: dict[str, Any] = {}
    for result in platform_results:
        if result.status != "ok":
            continue
        ids = sorted(ids_by_source.get(result.platform, set()))
        sources[result.platform] = {
            "prefix": SOURCE_PREFIXES.get(result.platform, ""),
            "seen_ids": ids,
            "total_visible": result.count,
            "total_unique_visible": len(ids),
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

    existing: dict[str, Any] = {}
    if memory_path.is_file() and memory_path.stat().st_size > 0:
        try:
            existing = json.loads(memory_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}

    merged = normalize_memory_payload(existing)
    update = normalize_memory_payload(memory_update, include_registry_defaults=False)
    merged["last_scan_at"] = update.get("last_scan_at")
    merged["scan_date"] = update.get("scan_date")
    merged_sources = merged.setdefault("sources", {})
    for source_key, state in update.get("sources", {}).items():
        merged_sources[source_key] = state

    write_memory_file(memory_path, merged)


def read_memory_export(memory_path: Path) -> str:
    if not memory_path.is_file() or memory_path.stat().st_size == 0:
        return ""
    return memory_path.read_text(encoding="utf-8")
