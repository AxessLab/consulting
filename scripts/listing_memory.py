"""Persistent per-source dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import (
    DEFAULT_SOURCES,
    SOURCE_REGISTRY,
    AssignmentRecord,
    SourceScanResult,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEMORY_PATH = REPO_ROOT / "assignment-listing-seen.json"
LEGACY_ALLAKONSULT_PATH = REPO_ROOT / "allakonsultuppdrag-seen.json"
LEGACY_VERAMA_PATH = REPO_ROOT / "verama-seen.json"


def _empty_source_state(source_key: str) -> dict[str, Any]:
    config = SOURCE_REGISTRY[source_key]
    return {
        "prefix": config.prefix,
        "seen_ids": [],
        "total_visible": 0,
        "total_unique_visible": 0,
    }


def _default_memory() -> dict[str, Any]:
    return {
        "last_scan_at": None,
        "scan_date": None,
        "sources": {source_key: _empty_source_state(source_key) for source_key in DEFAULT_SOURCES},
    }


def _collect_legacy_seen_ids(payload: dict[str, Any]) -> dict[str, set[str]]:
    seen: dict[str, set[str]] = {source_key: set() for source_key in DEFAULT_SOURCES}

    sources = payload.get("sources")
    if isinstance(sources, dict):
        for source_key, state in sources.items():
            if not isinstance(state, dict):
                continue
            ids = state.get("seen_ids")
            if isinstance(ids, list):
                seen.setdefault(source_key, set()).update(str(item) for item in ids)

    platforms = payload.get("platforms")
    if isinstance(platforms, dict):
        for source_key, state in platforms.items():
            if not isinstance(state, dict):
                continue
            ids = state.get("seen_ids")
            if isinstance(ids, list):
                seen.setdefault(source_key, set()).update(str(item) for item in ids)

    seen_keys = payload.get("seen_keys")
    if isinstance(seen_keys, list):
        for key in seen_keys:
            if not isinstance(key, str) or ":" not in key:
                continue
            source_key, source_id = key.split(":", 1)
            seen.setdefault(source_key, set()).add(source_id)

    legacy_seen = payload.get("seen_ids")
    if isinstance(legacy_seen, list):
        seen.setdefault("allakonsultuppdrag.se", set()).update(
            str(item) for item in legacy_seen
        )

    return seen


def _read_json_file(path: Path) -> dict[str, Any] | None:
    if not path.is_file() or path.stat().st_size == 0:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _read_legacy_single_source(path: Path) -> set[str]:
    payload = _read_json_file(path)
    if not payload:
        return set()
    if isinstance(payload.get("seen_ids"), list):
        return {str(item) for item in payload["seen_ids"]}
    if isinstance(payload.get("seen_keys"), list):
        ids: set[str] = set()
        for key in payload["seen_keys"]:
            if isinstance(key, str):
                ids.add(key.split(":", 1)[-1])
        return ids
    return set()


def normalize_memory_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return _default_memory()

    normalized = _default_memory()
    normalized["last_scan_at"] = payload.get("last_scan_at")
    normalized["scan_date"] = payload.get("scan_date")
    seen_by_source = _collect_legacy_seen_ids(payload)

    raw_sources = payload.get("sources")
    raw_platforms = payload.get("platforms")
    for source_key in DEFAULT_SOURCES:
        source_state = normalized["sources"][source_key]
        source_state["seen_ids"] = sorted(seen_by_source.get(source_key, set()))

        raw_state = None
        if isinstance(raw_sources, dict) and isinstance(raw_sources.get(source_key), dict):
            raw_state = raw_sources[source_key]
        elif isinstance(raw_platforms, dict) and isinstance(raw_platforms.get(source_key), dict):
            raw_state = raw_platforms[source_key]

        if raw_state:
            source_state["total_visible"] = int(raw_state.get("total_visible") or 0)
            source_state["total_unique_visible"] = int(
                raw_state.get("total_unique_visible")
                or raw_state.get("total_visible")
                or len(source_state["seen_ids"])
            )

    return normalized


def load_memory(path: Path) -> tuple[dict[str, set[str]], dict[str, Any]]:
    payload = _read_json_file(path)
    normalized = normalize_memory_payload(payload)

    if payload is None:
        legacy_allakonsult = _read_legacy_single_source(LEGACY_ALLAKONSULT_PATH)
        legacy_verama = _read_legacy_single_source(LEGACY_VERAMA_PATH)
        if legacy_allakonsult:
            normalized["sources"]["allakonsultuppdrag.se"]["seen_ids"] = sorted(
                legacy_allakonsult
            )
        if legacy_verama:
            normalized["sources"]["verama.com"]["seen_ids"] = sorted(legacy_verama)

    seen_by_source = {
        source_key: {str(item) for item in state.get("seen_ids", [])}
        for source_key, state in normalized.get("sources", {}).items()
        if isinstance(state, dict)
    }
    return seen_by_source, normalized


def collect_seen_keys(data: dict[str, Any]) -> set[str]:
    normalized = normalize_memory_payload(data)
    keys: set[str] = set()
    for source_key, state in normalized["sources"].items():
        for source_id in state.get("seen_ids", []):
            keys.add(f"{source_key}:{source_id}")
    return keys


def build_memory_payload(
    *,
    assignments: list[AssignmentRecord],
    source_results: list[SourceScanResult] | None = None,
    platform_results: list[SourceScanResult] | None = None,
    previous_memory: dict[str, Any] | None = None,
    scan_date: date,
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    normalized = normalize_memory_payload(previous_memory)
    normalized["last_scan_at"] = now
    normalized["scan_date"] = scan_date.isoformat()

    results = source_results if source_results is not None else platform_results or []
    successful_sources = {result.source_key for result in results if result.status == "ok"}
    by_source: dict[str, set[str]] = {source_key: set() for source_key in successful_sources}
    for assignment in assignments:
        if assignment.source_key in successful_sources:
            by_source.setdefault(assignment.source_key, set()).add(assignment.source_id)

    for result in results:
        if result.status != "ok":
            continue
        state = normalized["sources"].setdefault(
            result.source_key,
            _empty_source_state(result.source_key),
        )
        state["prefix"] = SOURCE_REGISTRY[result.source_key].prefix
        state["seen_ids"] = sorted(by_source.get(result.source_key, set()))
        state["total_visible"] = result.count
        state["total_unique_visible"] = len(by_source.get(result.source_key, set()))

    return normalized


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
