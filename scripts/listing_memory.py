"""Persistent per-source dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import AssignmentRecord, PlatformScanResult, SOURCE_REGISTRY

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEMORY_PATH = REPO_ROOT / "assignment-listing-seen.json"
LEGACY_ALLAKONSULT_PATH = REPO_ROOT / "allakonsultuppdrag-seen.json"


def _default_sources() -> dict[str, dict[str, Any]]:
    return {
        source.key: {
            "prefix": source.prefix,
            "seen_ids": [],
            "total_visible": 0,
            "total_unique_visible": 0,
        }
        for source in SOURCE_REGISTRY
    }


def _source_prefix(source_key: str) -> str:
    for source in SOURCE_REGISTRY:
        if source.key == source_key:
            return source.prefix
    return ""


def collect_seen_keys(data: dict[str, Any]) -> set[str]:
    """Read seen source keys from current or legacy memory shapes."""
    seen_keys: set[str] = set()

    sources = data.get("sources")
    if isinstance(sources, dict):
        for source_key, state in sources.items():
            if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
                for source_id in state["seen_ids"]:
                    seen_keys.add(f"{source_key}:{source_id}")

    legacy_seen_keys = data.get("seen_keys")
    if isinstance(legacy_seen_keys, list):
        for item in legacy_seen_keys:
            value = str(item)
            if ":" in value:
                seen_keys.add(value)

    legacy_platforms = data.get("platforms")
    if isinstance(legacy_platforms, dict):
        for source_key, state in legacy_platforms.items():
            if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
                for source_id in state["seen_ids"]:
                    seen_keys.add(f"{source_key}:{source_id}")

    legacy_seen = data.get("seen_ids")
    if isinstance(legacy_seen, list):
        for source_id in legacy_seen:
            seen_keys.add(f"allakonsultuppdrag.se:{source_id}")

    return seen_keys


def seen_ids_by_source(data: dict[str, Any]) -> dict[str, set[str]]:
    by_source: dict[str, set[str]] = {source.key: set() for source in SOURCE_REGISTRY}
    for key in collect_seen_keys(data):
        source_key, _, source_id = key.partition(":")
        if source_key and source_id:
            by_source.setdefault(source_key, set()).add(source_id)
    return by_source


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize current and legacy payloads into the unified sources shape."""
    seen_keys = collect_seen_keys(payload)
    sources = _default_sources()

    raw_sources = payload.get("sources")
    if isinstance(raw_sources, dict):
        for source_key, state in raw_sources.items():
            if not isinstance(state, dict):
                continue
            source_ids = [
                str(source_id)
                for source_id in state.get("seen_ids", [])
                if source_id is not None
            ]
            sources[source_key] = {
                "prefix": state.get("prefix") or _source_prefix(source_key),
                "seen_ids": sorted(set(source_ids)),
                "total_visible": int(state.get("total_visible") or len(set(source_ids))),
                "total_unique_visible": int(
                    state.get("total_unique_visible") or len(set(source_ids))
                ),
            }

    for key in seen_keys:
        source_key, _, source_id = key.partition(":")
        if not source_id:
            continue
        sources.setdefault(
            source_key,
            {
                "prefix": _source_prefix(source_key),
                "seen_ids": [],
                "total_visible": 0,
                "total_unique_visible": 0,
            },
        )
        sources[source_key]["seen_ids"] = sorted(
            set(sources[source_key].get("seen_ids", [])) | {source_id}
        )
        if not sources[source_key].get("total_visible"):
            sources[source_key]["total_visible"] = len(sources[source_key]["seen_ids"])
        if not sources[source_key].get("total_unique_visible"):
            sources[source_key]["total_unique_visible"] = len(
                sources[source_key]["seen_ids"]
            )

    normalized: dict[str, Any] = {
        "last_scan_at": payload.get("last_scan_at"),
        "scan_date": payload.get("scan_date"),
        "sources": sources,
    }
    return normalized


def _load_legacy_memory() -> dict[str, Any]:
    if not LEGACY_ALLAKONSULT_PATH.is_file() or LEGACY_ALLAKONSULT_PATH.stat().st_size == 0:
        return {}
    try:
        legacy = json.loads(LEGACY_ALLAKONSULT_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(legacy, dict):
        return {}
    return legacy


def load_memory(path: Path) -> tuple[set[str], dict[str, Any]]:
    if not path.is_file() or path.stat().st_size == 0:
        legacy = _load_legacy_memory()
        if legacy:
            normalized = normalize_memory_payload(legacy)
            return collect_seen_keys(normalized), normalized
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
    previous_memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    previous = normalize_memory_payload(previous_memory or {})
    sources = previous["sources"]

    for result in platform_results:
        if result.status != "ok":
            continue
        source_ids = sorted(
            {
                assignment.source_id
                for assignment in assignments
                if assignment.source_key == result.platform
            }
        )
        sources[result.platform] = {
            "prefix": _source_prefix(result.platform),
            "seen_ids": source_ids,
            "total_visible": result.count,
            "total_unique_visible": len(source_ids),
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
