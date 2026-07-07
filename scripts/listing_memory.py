"""Persistent per-source dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import (
    SOURCE_REGISTRY,
    AssignmentRecord,
    PlatformScanResult,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEMORY_PATH = REPO_ROOT / "assignment-listing-seen.json"
LEGACY_MEMORY_FILES = {
    "allakonsultuppdrag.se": REPO_ROOT / "allakonsultuppdrag-seen.json",
    "verama.com": REPO_ROOT / "verama-seen.json",
}


def empty_memory(scan_date: date | None = None) -> dict[str, Any]:
    return {
        "last_scan_at": None,
        "scan_date": scan_date.isoformat() if scan_date else None,
        "sources": {
            source_key: {
                "prefix": config.prefix,
                "seen_ids": [],
                "total_visible": 0,
                "total_unique_visible": 0,
            }
            for source_key, config in SOURCE_REGISTRY.items()
        },
    }


def _source_seen_ids(state: Any) -> set[str]:
    if not isinstance(state, dict) or not isinstance(state.get("seen_ids"), list):
        return set()
    return {str(item) for item in state["seen_ids"]}


def collect_seen_by_source(data: dict[str, Any]) -> dict[str, set[str]]:
    """Read source_id memory from current and legacy unified shapes."""
    seen_by_source = {source_key: set() for source_key in SOURCE_REGISTRY}

    sources = data.get("sources")
    if isinstance(sources, dict):
        for source_key, state in sources.items():
            if source_key in SOURCE_REGISTRY:
                seen_by_source[source_key].update(_source_seen_ids(state))

    legacy_platforms = data.get("platforms")
    if isinstance(legacy_platforms, dict):
        for source_key, state in legacy_platforms.items():
            if source_key in SOURCE_REGISTRY:
                seen_by_source[source_key].update(_source_seen_ids(state))

    legacy_seen_keys = data.get("seen_keys")
    if isinstance(legacy_seen_keys, list):
        for item in legacy_seen_keys:
            key = str(item)
            if ":" not in key:
                continue
            source_key, source_id = key.split(":", 1)
            if source_key in SOURCE_REGISTRY:
                seen_by_source[source_key].add(source_id)

    legacy_seen_ids = data.get("seen_ids")
    if isinstance(legacy_seen_ids, list):
        seen_by_source["allakonsultuppdrag.se"].update(str(item) for item in legacy_seen_ids)

    return seen_by_source


def collect_seen_keys(data: dict[str, Any]) -> set[str]:
    """Backward-compatible source_key:source_id set used by older call sites."""
    return {
        f"{source_key}:{source_id}"
        for source_key, seen_ids in collect_seen_by_source(data).items()
        for source_id in seen_ids
    }


def _load_legacy_single_source_files() -> dict[str, set[str]]:
    imported = {source_key: set() for source_key in SOURCE_REGISTRY}
    for source_key, path in LEGACY_MEMORY_FILES.items():
        if not path.is_file() or path.stat().st_size == 0:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        imported[source_key].update(collect_seen_by_source(payload).get(source_key, set()))
        if isinstance(payload.get("seen_ids"), list):
            imported[source_key].update(str(item) for item in payload["seen_ids"])
    return imported


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return valid unified memory with all registered sources present."""
    normalized = empty_memory()
    normalized["last_scan_at"] = payload.get("last_scan_at")
    normalized["scan_date"] = payload.get("scan_date")

    seen_by_source = collect_seen_by_source(payload)
    raw_sources = payload.get("sources") if isinstance(payload.get("sources"), dict) else {}
    for source_key, config in SOURCE_REGISTRY.items():
        raw_state = raw_sources.get(source_key, {}) if isinstance(raw_sources, dict) else {}
        if not isinstance(raw_state, dict):
            raw_state = {}
        normalized["sources"][source_key] = {
            "prefix": config.prefix,
            "seen_ids": sorted(seen_by_source.get(source_key, set())),
            "total_visible": int(raw_state.get("total_visible") or 0),
            "total_unique_visible": int(raw_state.get("total_unique_visible") or 0),
        }
    return normalized


def load_memory(path: Path) -> tuple[set[str], dict[str, Any]]:
    return collect_seen_keys(load_memory_payload(path)), load_memory_payload(path)


def load_memory_payload(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size == 0:
        payload = empty_memory()
    else:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raw = {}
        payload = normalize_memory_payload(raw if isinstance(raw, dict) else {})

    legacy_imports = _load_legacy_single_source_files()
    if any(legacy_imports.values()):
        sources = payload.setdefault("sources", {})
        for source_key, seen_ids in legacy_imports.items():
            if not seen_ids:
                continue
            state = sources.setdefault(
                source_key,
                {
                    "prefix": SOURCE_REGISTRY[source_key].prefix,
                    "seen_ids": [],
                    "total_visible": 0,
                    "total_unique_visible": 0,
                },
            )
            state["seen_ids"] = sorted(set(state.get("seen_ids", [])) | seen_ids)
        payload = normalize_memory_payload(payload)

    return payload


def load_seen_by_source(path: Path) -> tuple[dict[str, set[str]], dict[str, Any]]:
    payload = load_memory_payload(path)
    return collect_seen_by_source(payload), payload


def build_memory_payload(
    *,
    assignments: list[AssignmentRecord],
    platform_results: list[PlatformScanResult],
    scan_date: date,
    previous_memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    previous = normalize_memory_payload(previous_memory or {})
    now = datetime.now(UTC).isoformat()
    payload = normalize_memory_payload(previous)
    payload["last_scan_at"] = now
    payload["scan_date"] = scan_date.isoformat()

    assignments_by_source: dict[str, dict[str, AssignmentRecord]] = {
        source_key: {} for source_key in SOURCE_REGISTRY
    }
    for assignment in assignments:
        assignments_by_source.setdefault(assignment.source_key, {})[
            assignment.source_id
        ] = assignment

    for result in platform_results:
        source_key = result.platform
        if source_key not in SOURCE_REGISTRY:
            continue
        if result.status != "ok":
            continue
        visible = assignments_by_source.get(source_key, {})
        payload["sources"][source_key] = {
            "prefix": SOURCE_REGISTRY[source_key].prefix,
            "seen_ids": sorted(visible),
            "total_visible": result.count,
            "total_unique_visible": result.total_unique_visible
            if result.total_unique_visible is not None
            else len(visible),
        }

    return payload


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
