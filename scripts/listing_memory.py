"""Persistent dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import AssignmentRecord, PlatformScanResult, SOURCE_REGISTRY

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEMORY_PATH = REPO_ROOT / "assignment-listing-seen.json"
LEGACY_MEMORY_FILES = {
    "allakonsultuppdrag.se": REPO_ROOT / "allakonsultuppdrag-seen.json",
    "verama.com": REPO_ROOT / "verama-seen.json",
}


def _empty_source_state(source_key: str) -> dict[str, Any]:
    return {
        "prefix": SOURCE_REGISTRY.get(source_key, {}).get("prefix", ""),
        "seen_ids": [],
        "total_visible": 0,
        "total_unique_visible": 0,
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if path.is_file() and path.stat().st_size > 0:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}
    return {}


def collect_seen_ids_by_source(data: dict[str, Any]) -> dict[str, set[str]]:
    """Read bare native ids per source from current and legacy memory shapes."""
    by_source: dict[str, set[str]] = {source: set() for source in SOURCE_REGISTRY}

    sources = data.get("sources")
    if isinstance(sources, dict):
        for source_key, state in sources.items():
            if not isinstance(state, dict) or not isinstance(state.get("seen_ids"), list):
                continue
            by_source.setdefault(source_key, set()).update(str(item) for item in state["seen_ids"])

    if isinstance(data.get("seen_keys"), list):
        for item in data["seen_keys"]:
            source_key, _, source_id = str(item).partition(":")
            if source_key and source_id:
                by_source.setdefault(source_key, set()).add(source_id)

    platforms = data.get("platforms")
    if isinstance(platforms, dict):
        for platform_id, state in platforms.items():
            if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
                for source_id in state["seen_ids"]:
                    by_source.setdefault(platform_id, set()).add(str(source_id))

    legacy_seen = data.get("seen_ids")
    if isinstance(legacy_seen, list):
        for source_id in legacy_seen:
            by_source.setdefault("allakonsultuppdrag.se", set()).add(str(source_id))

    return by_source


def collect_seen_keys(data: dict[str, Any]) -> set[str]:
    """Read seen dedupe keys from current or legacy memory shapes."""
    return {
        f"{source_key}:{source_id}"
        for source_key, source_ids in collect_seen_ids_by_source(data).items()
        for source_id in source_ids
    }


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize memory to the unified per-source shape."""
    seen_by_source = collect_seen_ids_by_source(payload)
    raw_sources = payload.get("sources") if isinstance(payload.get("sources"), dict) else {}
    sources: dict[str, Any] = {}
    for source_key in SOURCE_REGISTRY:
        raw_state = raw_sources.get(source_key, {}) if isinstance(raw_sources, dict) else {}
        source_ids = sorted(seen_by_source.get(source_key, set()))
        sources[source_key] = {
            "prefix": SOURCE_REGISTRY[source_key]["prefix"],
            "seen_ids": source_ids,
            "total_visible": raw_state.get("total_visible", len(source_ids))
            if isinstance(raw_state, dict)
            else len(source_ids),
            "total_unique_visible": raw_state.get("total_unique_visible", len(source_ids))
            if isinstance(raw_state, dict)
            else len(source_ids),
        }

    normalized: dict[str, Any] = {
        "last_scan_at": payload.get("last_scan_at"),
        "scan_date": payload.get("scan_date"),
        "sources": sources,
    }
    return normalized


def load_memory(path: Path) -> tuple[set[str], dict[str, Any]]:
    data = _read_json(path)
    if not data:
        legacy_sources: dict[str, Any] = {}
        for source_key, legacy_path in LEGACY_MEMORY_FILES.items():
            legacy_payload = _read_json(legacy_path)
            source_ids = sorted(collect_seen_ids_by_source(legacy_payload).get(source_key, set()))
            if source_ids:
                legacy_sources[source_key] = {
                    "prefix": SOURCE_REGISTRY[source_key]["prefix"],
                    "seen_ids": source_ids,
                    "total_visible": len(source_ids),
                    "total_unique_visible": len(source_ids),
                }
        if legacy_sources:
            data = {"sources": legacy_sources}

    return collect_seen_keys(data), data


def seen_ids_by_source(data: dict[str, Any]) -> dict[str, set[str]]:
    return collect_seen_ids_by_source(data)


def build_memory_payload(
    *,
    assignments: list[AssignmentRecord],
    platform_results: list[PlatformScanResult],
    scan_date: date,
    previous_memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    previous = normalize_memory_payload(previous_memory or {})
    previous_sources = previous.get("sources") if isinstance(previous.get("sources"), dict) else {}
    ids_by_source: dict[str, set[str]] = {source: set() for source in SOURCE_REGISTRY}
    for assignment in assignments:
        ids_by_source.setdefault(assignment.platform, set()).add(assignment.source_id)

    results_by_source = {result.platform: result for result in platform_results}
    sources: dict[str, Any] = {}
    total_visible = 0
    total_unique_visible = 0
    for result in platform_results:
        if result.status != "ok":
            continue
        total_visible += result.count
        total_unique_visible += len(ids_by_source.get(result.platform, set()))

    for source_key in SOURCE_REGISTRY:
        result = results_by_source.get(source_key)
        if result and result.status == "ok":
            source_ids = sorted(ids_by_source.get(source_key, set()))
            sources[source_key] = {
                "prefix": SOURCE_REGISTRY[source_key]["prefix"],
                "seen_ids": source_ids,
                "total_visible": result.count,
                "total_unique_visible": len(source_ids),
            }
            continue

        prior = previous_sources.get(source_key) if isinstance(previous_sources, dict) else None
        if isinstance(prior, dict):
            sources[source_key] = {
                "prefix": SOURCE_REGISTRY[source_key]["prefix"],
                "seen_ids": [str(item) for item in prior.get("seen_ids", [])],
                "total_visible": prior.get("total_visible", 0),
                "total_unique_visible": prior.get("total_unique_visible", 0),
            }
        else:
            sources[source_key] = _empty_source_state(source_key)

    return {
        "last_scan_at": now,
        "scan_date": scan_date.isoformat(),
        "sources": sources,
        "scan_results": {
            result.platform: {
                "status": result.status,
                "total_visible": result.count,
                **({"message": result.message} if result.message else {}),
            }
            for result in platform_results
        }
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
