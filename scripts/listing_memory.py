"""Persistent per-source dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import AssignmentRecord, PlatformScanResult, SOURCE_REGISTRY

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEMORY_PATH = REPO_ROOT / "assignment-listing-seen.json"
LEGACY_MEMORY_PATHS = {
    "allakonsultuppdrag.se": REPO_ROOT / "allakonsultuppdrag-seen.json",
    "verama.com": REPO_ROOT / "verama-seen.json",
}


def _empty_memory() -> dict[str, Any]:
    return {
        "last_scan_at": None,
        "scan_date": None,
        "sources": {
            source_key: {
                "prefix": spec.prefix,
                "seen_ids": [],
                "total_visible": 0,
                "total_unique_visible": 0,
            }
            for source_key, spec in SOURCE_REGISTRY.items()
        },
    }


def collect_seen_ids_by_source(data: dict[str, Any]) -> dict[str, set[str]]:
    seen: dict[str, set[str]] = {source_key: set() for source_key in SOURCE_REGISTRY}

    sources = data.get("sources")
    if isinstance(sources, dict):
        for source_key, state in sources.items():
            if source_key not in SOURCE_REGISTRY or not isinstance(state, dict):
                continue
            if isinstance(state.get("seen_ids"), list):
                seen[source_key].update(str(item) for item in state["seen_ids"])

    # Previous in-repo shape.
    platforms = data.get("platforms")
    if isinstance(platforms, dict):
        for source_key, state in platforms.items():
            if source_key not in SOURCE_REGISTRY or not isinstance(state, dict):
                continue
            if isinstance(state.get("seen_ids"), list):
                seen[source_key].update(str(item) for item in state["seen_ids"])

    # Older unified shape.
    if isinstance(data.get("seen_keys"), list):
        for item in data["seen_keys"]:
            source_key, sep, source_id = str(item).partition(":")
            if sep and source_key in SOURCE_REGISTRY and source_id:
                seen[source_key].add(source_id)

    # Old allakonsult-only shape.
    if isinstance(data.get("seen_ids"), list):
        seen["allakonsultuppdrag.se"].update(str(item) for item in data["seen_ids"])

    return seen


def collect_seen_keys(data: dict[str, Any]) -> set[str]:
    """Read seen dedupe keys from current or legacy memory shapes."""
    seen_keys: set[str] = set()
    for source_key, source_ids in collect_seen_ids_by_source(data).items():
        seen_keys.update(f"{source_key}:{source_id}" for source_id in source_ids)
    return seen_keys


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize to the current unified `sources` memory shape."""
    normalized = _empty_memory()
    normalized["last_scan_at"] = payload.get("last_scan_at")
    normalized["scan_date"] = payload.get("scan_date")
    seen_by_source = collect_seen_ids_by_source(payload)

    raw_sources = payload.get("sources") if isinstance(payload.get("sources"), dict) else {}
    for source_key, spec in SOURCE_REGISTRY.items():
        raw_state = raw_sources.get(source_key, {}) if isinstance(raw_sources, dict) else {}
        if not isinstance(raw_state, dict):
            raw_state = {}
        source_seen = seen_by_source.get(source_key, set())
        normalized["sources"][source_key] = {
            "prefix": spec.prefix,
            "seen_ids": sorted(source_seen, key=lambda value: (len(value), value)),
            "total_visible": int(raw_state.get("total_visible") or len(source_seen)),
            "total_unique_visible": int(
                raw_state.get("total_unique_visible") or len(source_seen)
            ),
        }
    return normalized


def load_memory(path: Path) -> tuple[set[str], dict[str, Any]]:
    if not path.is_file() or path.stat().st_size == 0:
        data = _load_legacy_memory()
        return collect_seen_keys(data), data
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        data = _load_legacy_memory()

    normalized = normalize_memory_payload(data)
    return collect_seen_keys(normalized), normalized


def _load_legacy_memory() -> dict[str, Any]:
    data = _empty_memory()
    imported_any = False
    for source_key, path in LEGACY_MEMORY_PATHS.items():
        if not path.is_file() or path.stat().st_size == 0:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        seen_ids = payload.get("seen_ids")
        if isinstance(seen_ids, list):
            data["sources"][source_key]["seen_ids"] = [str(item) for item in seen_ids]
            imported_any = True
    return data if imported_any else {}


def build_memory_payload(
    *,
    assignments: list[AssignmentRecord],
    platform_results: list[PlatformScanResult],
    scan_date: date,
    existing_memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    memory = normalize_memory_payload(existing_memory or {})
    by_source: dict[str, set[str]] = {source_key: set() for source_key in SOURCE_REGISTRY}
    for assignment in assignments:
        if assignment.source_key in by_source:
            by_source[assignment.source_key].add(assignment.source_id)

    for result in platform_results:
        if result.status != "ok" or result.platform not in SOURCE_REGISTRY:
            continue
        source_ids = by_source.get(result.platform, set())
        memory["sources"][result.platform] = {
            "prefix": SOURCE_REGISTRY[result.platform].prefix,
            "seen_ids": sorted(source_ids, key=lambda value: (len(value), value)),
            "total_visible": result.count,
            "total_unique_visible": len(source_ids),
        }

    memory["last_scan_at"] = now
    memory["scan_date"] = scan_date.isoformat()
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
