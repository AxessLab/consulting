"""Persistent per-source dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import AssignmentRecord, PlatformScanResult, SOURCE_REGISTRY

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEMORY_PATH = REPO_ROOT / "assignment-listing-seen.json"


def _default_source_state(source_key: str) -> dict[str, Any]:
    return {
        "prefix": SOURCE_REGISTRY[source_key].prefix,
        "seen_ids": [],
        "total_visible": 0,
        "total_unique_visible": 0,
    }


def _normalize_seen_ids(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return sorted({str(item) for item in values})


def normalize_memory_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Return the unified `sources` memory shape, migrating legacy variants."""
    payload = payload or {}
    sources: dict[str, dict[str, Any]] = {
        source_key: _default_source_state(source_key) for source_key in SOURCE_REGISTRY
    }

    raw_sources = payload.get("sources")
    if isinstance(raw_sources, dict):
        for source_key, state in raw_sources.items():
            if source_key not in SOURCE_REGISTRY or not isinstance(state, dict):
                continue
            seen_ids = _normalize_seen_ids(state.get("seen_ids"))
            sources[source_key] = {
                "prefix": SOURCE_REGISTRY[source_key].prefix,
                "seen_ids": seen_ids,
                "total_visible": int(state.get("total_visible") or len(seen_ids)),
                "total_unique_visible": int(
                    state.get("total_unique_visible") or len(seen_ids)
                ),
            }

    legacy_platforms = payload.get("platforms")
    if isinstance(legacy_platforms, dict):
        for source_key, state in legacy_platforms.items():
            if source_key not in SOURCE_REGISTRY or not isinstance(state, dict):
                continue
            seen_ids = _normalize_seen_ids(state.get("seen_ids"))
            if seen_ids:
                sources[source_key]["seen_ids"] = seen_ids
                sources[source_key]["total_visible"] = int(
                    state.get("total_visible") or len(seen_ids)
                )
                sources[source_key]["total_unique_visible"] = int(
                    state.get("total_unique_visible") or len(seen_ids)
                )

    legacy_seen_keys = payload.get("seen_keys")
    if isinstance(legacy_seen_keys, list):
        for item in legacy_seen_keys:
            source_key, separator, source_id = str(item).partition(":")
            if separator and source_key in sources:
                sources[source_key]["seen_ids"].append(source_id)

    legacy_allakonsult_ids = payload.get("seen_ids")
    if isinstance(legacy_allakonsult_ids, list):
        sources["allakonsultuppdrag.se"]["seen_ids"].extend(
            str(item) for item in legacy_allakonsult_ids
        )

    for source_key, state in sources.items():
        state["prefix"] = SOURCE_REGISTRY[source_key].prefix
        state["seen_ids"] = sorted({str(item) for item in state.get("seen_ids", [])})
        state["total_visible"] = int(state.get("total_visible") or len(state["seen_ids"]))
        state["total_unique_visible"] = int(
            state.get("total_unique_visible") or len(state["seen_ids"])
        )

    return {
        "last_scan_at": payload.get("last_scan_at"),
        "scan_date": payload.get("scan_date"),
        "sources": sources,
    }


def seen_ids_by_source(data: dict[str, Any] | None) -> dict[str, set[str]]:
    normalized = normalize_memory_payload(data)
    return {
        source_key: set(state.get("seen_ids") or [])
        for source_key, state in normalized["sources"].items()
    }


def collect_seen_keys(data: dict[str, Any]) -> set[str]:
    """Read source-key-prefixed seen ids from current or legacy memory shapes."""
    seen_keys: set[str] = set()
    for source_key, ids in seen_ids_by_source(data).items():
        seen_keys.update(f"{source_key}:{source_id}" for source_id in ids)

    return seen_keys


def load_memory(path: Path) -> tuple[set[str], dict[str, Any]]:
    if not path.is_file() or path.stat().st_size == 0:
        return set(), normalize_memory_payload({})
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set(), normalize_memory_payload({})

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
    normalized = normalize_memory_payload(previous_memory)
    sources: dict[str, dict[str, Any]] = {
        source_key: {
            "prefix": state["prefix"],
            "seen_ids": list(state.get("seen_ids") or []),
            "total_visible": int(state.get("total_visible") or 0),
            "total_unique_visible": int(state.get("total_unique_visible") or 0),
        }
        for source_key, state in normalized["sources"].items()
    }

    visible_by_source: dict[str, set[str]] = {source_key: set() for source_key in sources}
    for assignment in assignments:
        visible_by_source.setdefault(assignment.source_key, set()).add(assignment.source_id)

    for result in platform_results:
        if result.status != "ok":
            continue
        source_key = result.source_key
        seen_ids = sorted(visible_by_source.get(source_key, set()))
        sources[source_key] = {
            "prefix": SOURCE_REGISTRY[source_key].prefix,
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
