"""Persistent per-source dedupe memory for assignment listing runs."""

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


def _default_sources() -> dict[str, dict[str, Any]]:
    return {
        source.source_key: {
            "prefix": source.prefix,
            "seen_ids": [],
            "total_visible": 0,
            "total_unique_visible": 0,
        }
        for source in SOURCE_REGISTRY
    }


def _coerce_seen_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({str(item) for item in value})


def collect_seen_ids_by_source(data: dict[str, Any]) -> dict[str, set[str]]:
    """Read per-source bare ids from current and legacy memory shapes."""
    seen: dict[str, set[str]] = {source.source_key: set() for source in SOURCE_REGISTRY}

    sources = data.get("sources")
    if isinstance(sources, dict):
        for source_key, state in sources.items():
            if not isinstance(state, dict):
                continue
            if isinstance(state.get("seen_ids"), list):
                seen.setdefault(source_key, set()).update(str(item) for item in state["seen_ids"])

    # Previous multi-platform implementation stored platform:source_id strings.
    if isinstance(data.get("seen_keys"), list):
        for key in data["seen_keys"]:
            source_key, sep, source_id = str(key).partition(":")
            if sep and source_id:
                seen.setdefault(source_key, set()).add(source_id)

    # Earlier transitional shape used platforms.<key>.seen_ids.
    platforms = data.get("platforms")
    if isinstance(platforms, dict):
        for source_key, state in platforms.items():
            if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
                seen.setdefault(source_key, set()).update(str(item) for item in state["seen_ids"])

    # Original single-source file shape.
    if isinstance(data.get("seen_ids"), list):
        seen.setdefault("allakonsultuppdrag.se", set()).update(str(item) for item in data["seen_ids"])

    return seen


def collect_seen_keys(data: dict[str, Any]) -> set[str]:
    return {
        f"{source_key}:{source_id}"
        for source_key, ids in collect_seen_ids_by_source(data).items()
        for source_id in ids
    }


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size == 0:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _merge_legacy_files(seen_by_source: dict[str, set[str]]) -> None:
    for source_key, path in LEGACY_MEMORY_FILES.items():
        payload = _read_json_file(path)
        if not payload:
            continue
        seen_by_source.setdefault(source_key, set()).update(
            collect_seen_ids_by_source(payload).get(source_key, set())
        )
        if isinstance(payload.get("seen_ids"), list):
            seen_by_source.setdefault(source_key, set()).update(str(item) for item in payload["seen_ids"])


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    seen_by_source = collect_seen_ids_by_source(payload)
    sources = _default_sources()

    raw_sources = payload.get("sources")
    if isinstance(raw_sources, dict):
        for source_key, state in raw_sources.items():
            if source_key not in sources or not isinstance(state, dict):
                continue
            sources[source_key]["total_visible"] = int(state.get("total_visible") or 0)
            sources[source_key]["total_unique_visible"] = int(state.get("total_unique_visible") or 0)

    for source_key, ids in seen_by_source.items():
        if source_key not in sources:
            continue
        sources[source_key]["seen_ids"] = sorted(ids, key=lambda value: (len(value), value))

    return {
        "last_scan_at": payload.get("last_scan_at"),
        "scan_date": payload.get("scan_date"),
        "sources": sources,
    }


def load_memory(path: Path) -> tuple[set[str], dict[str, Any]]:
    data = _read_json_file(path)
    seen_by_source = collect_seen_ids_by_source(data)
    _merge_legacy_files(seen_by_source)
    if not data and not any(seen_by_source.values()):
        return set(), normalize_memory_payload({})
    merged = normalize_memory_payload({**data, "sources": {
        **(data.get("sources") if isinstance(data.get("sources"), dict) else {}),
        **{
            source_key: {
                **((data.get("sources") or {}).get(source_key, {}) if isinstance(data.get("sources"), dict) else {}),
                "seen_ids": sorted(ids),
            }
            for source_key, ids in seen_by_source.items()
        },
    }})
    return collect_seen_keys(merged), merged


def load_seen_ids_by_source(path: Path) -> tuple[dict[str, set[str]], dict[str, Any]]:
    _, memory = load_memory(path)
    return collect_seen_ids_by_source(memory), memory


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

    successful_sources = {result.source_key for result in platform_results if result.status == "ok"}
    visible_by_source: dict[str, set[str]] = {source_key: set() for source_key in successful_sources}
    for assignment in assignments:
        if assignment.source_key in successful_sources:
            visible_by_source.setdefault(assignment.source_key, set()).add(assignment.source_id)

    for result in platform_results:
        if result.status != "ok":
            continue
        source_state = payload["sources"].setdefault(
            result.source_key,
            {
                "prefix": "",
                "seen_ids": [],
                "total_visible": 0,
                "total_unique_visible": 0,
            },
        )
        visible_ids = sorted(visible_by_source.get(result.source_key, set()), key=lambda value: (len(value), value))
        source_state["seen_ids"] = visible_ids
        source_state["total_visible"] = result.count
        source_state["total_unique_visible"] = len(visible_ids)

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
