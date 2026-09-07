"""Persistent dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import AssignmentRecord, PlatformScanResult

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEMORY_PATH = REPO_ROOT / "assignment-listing-seen.json"
SOURCE_PREFIXES: dict[str, str] = {
    "allakonsultuppdrag.se": "a",
    "verama.com": "v",
    "chaspartnernetwork.se": "c",
    "magnit-source.magnitglobal.com": "m",
    "cinode.com/market": "n",
}


def collect_seen_keys(data: dict[str, Any]) -> set[str]:
    """Read seen dedupe keys from current or legacy memory shapes."""
    seen_keys: set[str] = set()
    if isinstance(data.get("seen_keys"), list):
        seen_keys.update(str(item) for item in data["seen_keys"])

    sources = data.get("sources")
    if isinstance(sources, dict):
        for source_key, state in sources.items():
            if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
                for source_id in state["seen_ids"]:
                    seen_keys.add(f"{source_key}:{source_id}")

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


def _split_seen_keys_by_source(seen_keys: set[str]) -> dict[str, set[str]]:
    by_source: dict[str, set[str]] = {}
    for key in seen_keys:
        if ":" not in key:
            continue
        source_key, source_id = key.split(":", 1)
        by_source.setdefault(source_key, set()).add(source_id)
    return by_source


def _source_state_from_payload(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_sources = payload.get("sources")
    if isinstance(raw_sources, dict):
        return {
            source_key: dict(state)
            for source_key, state in raw_sources.items()
            if isinstance(state, dict)
        }

    seen_by_source = _split_seen_keys_by_source(collect_seen_keys(payload))
    raw_platforms = payload.get("platforms")
    sources: dict[str, dict[str, Any]] = {}
    for source_key, source_ids in seen_by_source.items():
        state = raw_platforms.get(source_key, {}) if isinstance(raw_platforms, dict) else {}
        sources[source_key] = {
            "prefix": SOURCE_PREFIXES.get(source_key, ""),
            "seen_ids": sorted(source_ids),
            "total_visible": state.get("total_visible", len(source_ids))
            if isinstance(state, dict)
            else len(source_ids),
            "total_unique_visible": state.get("total_unique_visible", len(source_ids))
            if isinstance(state, dict)
            else len(source_ids),
        }
    return sources


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize memory to the per-source contract used by listing automations."""
    raw_sources = _source_state_from_payload(payload)
    sources: dict[str, Any] = {}
    for source_key, prefix in SOURCE_PREFIXES.items():
        state = raw_sources.get(source_key, {})
        seen_ids = [str(item) for item in state.get("seen_ids", [])]
        total_visible = state.get("total_visible", len(seen_ids))
        total_unique_visible = state.get("total_unique_visible", len(seen_ids))
        sources[source_key] = {
            "prefix": state.get("prefix") or prefix,
            "seen_ids": sorted(dict.fromkeys(seen_ids)),
            "total_visible": int(total_visible or 0),
            "total_unique_visible": int(total_unique_visible or 0),
        }

    for source_key, state in raw_sources.items():
        if source_key in sources or not isinstance(state, dict):
            continue
        seen_ids = [str(item) for item in state.get("seen_ids", [])]
        sources[source_key] = {
            "prefix": state.get("prefix") or "",
            "seen_ids": sorted(dict.fromkeys(seen_ids)),
            "total_visible": int(state.get("total_visible") or len(seen_ids)),
            "total_unique_visible": int(state.get("total_unique_visible") or len(seen_ids)),
        }

    normalized: dict[str, Any] = {
        "source": payload.get("source", "multi-platform assignment listing"),
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
    existing_memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    existing_sources = _source_state_from_payload(existing_memory or {})
    sources: dict[str, Any] = {}
    visible_by_source: dict[str, set[str]] = {}
    for assignment in assignments:
        visible_by_source.setdefault(assignment.platform, set()).add(assignment.source_id)

    for result in platform_results:
        existing = existing_sources.get(result.platform, {})
        if result.status != "ok":
            if existing:
                sources[result.platform] = existing
            continue

        seen_ids = sorted(visible_by_source.get(result.platform, set()))
        sources[result.platform] = {
            "prefix": SOURCE_PREFIXES.get(result.platform, existing.get("prefix", "")),
            "seen_ids": seen_ids,
            "total_visible": result.count,
            "total_unique_visible": len(seen_ids),
        }

    for source_key, state in existing_sources.items():
        sources.setdefault(source_key, state)

    return {
        "source": "multi-platform assignment listing",
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
