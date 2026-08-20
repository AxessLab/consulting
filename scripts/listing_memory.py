"""Persistent dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import AssignmentRecord, PlatformScanResult, SOURCE_PREFIXES, SOURCE_ORDER

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEMORY_PATH = REPO_ROOT / "assignment-listing-seen.json"


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


def collect_seen_ids_by_source(data: dict[str, Any]) -> dict[str, set[str]]:
    """Return native ids grouped by source key from current or legacy memory."""
    grouped: dict[str, set[str]] = {source_key: set() for source_key in SOURCE_ORDER}
    for seen_key in collect_seen_keys(data):
        if ":" not in seen_key:
            continue
        source_key, source_id = seen_key.split(":", 1)
        grouped.setdefault(source_key, set()).add(source_id)
    return grouped


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize current and legacy memory into the source-scoped shape."""
    seen_by_source = collect_seen_ids_by_source(payload)
    raw_sources = payload.get("sources")
    sources: dict[str, Any] = {}
    for source_key in SOURCE_ORDER:
        raw_state = raw_sources.get(source_key, {}) if isinstance(raw_sources, dict) else {}
        if not isinstance(raw_state, dict):
            raw_state = {}
        seen_ids = sorted(seen_by_source.get(source_key, set()), key=str)
        sources[source_key] = {
            "prefix": raw_state.get("prefix") or SOURCE_PREFIXES.get(source_key, ""),
            "seen_ids": seen_ids,
            "total_visible": int(raw_state.get("total_visible") or len(seen_ids)),
            "total_unique_visible": int(
                raw_state.get("total_unique_visible") or len(seen_ids)
            ),
        }

    for source_key, seen_ids_set in seen_by_source.items():
        if source_key in sources:
            continue
        seen_ids = sorted(seen_ids_set, key=str)
        sources[source_key] = {
            "prefix": "",
            "seen_ids": seen_ids,
            "total_visible": len(seen_ids),
            "total_unique_visible": len(seen_ids),
        }

    normalized: dict[str, Any] = {
        "source": payload.get("source", "multi-platform assignment listing"),
        "last_scan_at": payload.get("last_scan_at"),
        "scan_date": payload.get("scan_date"),
        "sources": sources,
        "total_visible": payload.get(
            "total_visible",
            sum(state["total_visible"] for state in sources.values()),
        ),
        "total_unique_visible": payload.get(
            "total_unique_visible",
            sum(state["total_unique_visible"] for state in sources.values()),
        ),
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
    previous_memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    payload = normalize_memory_payload(previous_memory or {})
    sources = payload["sources"]

    for result in platform_results:
        source_key = result.platform
        if source_key not in sources:
            sources[source_key] = {
                "prefix": SOURCE_PREFIXES.get(source_key, ""),
                "seen_ids": [],
                "total_visible": 0,
                "total_unique_visible": 0,
            }
        if result.status != "ok":
            continue
        visible_ids = sorted(
            {
                assignment.source_id
                for assignment in assignments
                if assignment.platform == source_key
            },
            key=str,
        )
        sources[source_key] = {
            "prefix": SOURCE_PREFIXES.get(source_key, sources[source_key].get("prefix", "")),
            "seen_ids": visible_ids,
            "total_visible": result.count,
            "total_unique_visible": len(visible_ids),
        }

    return {
        "source": "multi-platform assignment listing",
        "last_scan_at": now,
        "scan_date": scan_date.isoformat(),
        "sources": sources,
        "total_visible": sum(state["total_visible"] for state in sources.values()),
        "total_unique_visible": sum(
            state["total_unique_visible"] for state in sources.values()
        ),
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
