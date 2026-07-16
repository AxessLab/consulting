"""Persistent dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import AssignmentRecord, PlatformScanResult, SOURCE_REGISTRY

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEMORY_PATH = REPO_ROOT / "assignment-listing-seen.json"


def default_source_state(source_key: str) -> dict[str, Any]:
    config = SOURCE_REGISTRY[source_key]
    return {
        "prefix": config.prefix,
        "seen_ids": [],
        "total_visible": 0,
        "total_unique_visible": 0,
    }


def _empty_memory() -> dict[str, Any]:
    return {
        "last_scan_at": None,
        "scan_date": None,
        "sources": {source_key: default_source_state(source_key) for source_key in SOURCE_REGISTRY},
    }


def _legacy_seen_ids_for_source(data: dict[str, Any], source_key: str) -> set[str]:
    seen: set[str] = set()

    legacy_sources = data.get("sources")
    if isinstance(legacy_sources, dict):
        state = legacy_sources.get(source_key)
        if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
            seen.update(str(item) for item in state["seen_ids"])

    legacy_platforms = data.get("platforms")
    if isinstance(legacy_platforms, dict):
        state = legacy_platforms.get(source_key)
        if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
            seen.update(str(item) for item in state["seen_ids"])

    if isinstance(data.get("seen_keys"), list):
        prefix = f"{source_key}:"
        for item in data["seen_keys"]:
            value = str(item)
            if value.startswith(prefix):
                seen.add(value[len(prefix) :])

    if source_key == "allakonsultuppdrag.se" and isinstance(data.get("seen_ids"), list):
        seen.update(str(item) for item in data["seen_ids"])

    return seen


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize current and legacy payloads into the unified sources shape."""
    if not isinstance(payload, dict):
        return _empty_memory()

    normalized = _empty_memory()
    normalized["last_scan_at"] = payload.get("last_scan_at")
    normalized["scan_date"] = payload.get("scan_date")

    raw_sources = payload.get("sources")
    raw_platforms = payload.get("platforms")
    for source_key in SOURCE_REGISTRY:
        state = default_source_state(source_key)
        seen_ids = _legacy_seen_ids_for_source(payload, source_key)

        raw_state = None
        if isinstance(raw_sources, dict) and isinstance(raw_sources.get(source_key), dict):
            raw_state = raw_sources[source_key]
        elif isinstance(raw_platforms, dict) and isinstance(raw_platforms.get(source_key), dict):
            raw_state = raw_platforms[source_key]

        if raw_state:
            state["total_visible"] = int(raw_state.get("total_visible") or 0)
            state["total_unique_visible"] = int(raw_state.get("total_unique_visible") or len(seen_ids))
        state["seen_ids"] = sorted(seen_ids, key=lambda value: (len(value), value))
        normalized["sources"][source_key] = state

    return normalized


def seen_ids_by_source(data: dict[str, Any]) -> dict[str, set[str]]:
    normalized = normalize_memory_payload(data)
    result: dict[str, set[str]] = {}
    for source_key, state in normalized.get("sources", {}).items():
        seen_ids = state.get("seen_ids")
        result[source_key] = {str(item) for item in seen_ids} if isinstance(seen_ids, list) else set()
    return result


def collect_seen_keys(data: dict[str, Any]) -> set[str]:
    return {
        f"{source_key}:{source_id}"
        for source_key, source_seen_ids in seen_ids_by_source(data).items()
        for source_id in source_seen_ids
    }


def load_memory(path: Path) -> tuple[set[str], dict[str, Any]]:
    if not path.is_file() or path.stat().st_size == 0:
        data = _empty_memory()
        return set(), data
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        data = _empty_memory()
        return set(), data
    if not isinstance(raw, dict):
        data = _empty_memory()
        return set(), data
    data = normalize_memory_payload(raw)
    return collect_seen_keys(data), data


def load_seen_ids_by_source(path: Path) -> tuple[dict[str, set[str]], dict[str, Any]]:
    _, data = load_memory(path)
    return seen_ids_by_source(data), data


def build_memory_payload(
    *,
    assignments: list[AssignmentRecord],
    platform_results: list[PlatformScanResult],
    scan_date: date,
    existing_memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a memory payload while preserving failed/skipped source state."""
    memory = normalize_memory_payload(existing_memory or {})
    memory["last_scan_at"] = datetime.now(UTC).isoformat()
    memory["scan_date"] = scan_date.isoformat()

    ids_by_source: dict[str, set[str]] = {source_key: set() for source_key in SOURCE_REGISTRY}
    for assignment in assignments:
        ids_by_source.setdefault(assignment.source_key, set()).add(assignment.source_id)

    for result in platform_results:
        if result.status != "ok":
            continue
        state = default_source_state(result.source_key)
        ids = ids_by_source.get(result.source_key, set())
        state["seen_ids"] = sorted(ids, key=lambda value: (len(value), value))
        state["total_visible"] = int(result.total_visible or result.count)
        state["total_unique_visible"] = int(result.total_unique_visible or len(ids))
        memory["sources"][result.source_key] = state

    return memory


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
