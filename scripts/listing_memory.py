"""Persistent dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import AssignmentRecord, PlatformScanResult, SOURCE_REGISTRY

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


def _default_source_entry(source_key: str) -> dict[str, Any]:
    return {
        "prefix": SOURCE_REGISTRY[source_key]["prefix"],
        "seen_ids": [],
        "total_visible": 0,
        "total_unique_visible": 0,
    }


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize current or legacy payloads to the unified per-source memory shape."""
    seen_keys = collect_seen_keys(payload)
    sources: dict[str, Any] = {}
    raw_sources = payload.get("sources")
    for source_key in SOURCE_REGISTRY:
        entry = _default_source_entry(source_key)
        if isinstance(raw_sources, dict) and isinstance(raw_sources.get(source_key), dict):
            state = raw_sources[source_key]
            entry["seen_ids"] = [str(item) for item in state.get("seen_ids") or []]
            entry["total_visible"] = int(state.get("total_visible") or len(entry["seen_ids"]))
            entry["total_unique_visible"] = int(
                state.get("total_unique_visible") or len(set(entry["seen_ids"]))
            )
        else:
            prefix = f"{source_key}:"
            entry["seen_ids"] = sorted(
                key.removeprefix(prefix) for key in seen_keys if key.startswith(prefix)
            )
            entry["total_visible"] = len(entry["seen_ids"])
            entry["total_unique_visible"] = len(set(entry["seen_ids"]))
        sources[source_key] = entry

    normalized: dict[str, Any] = {
        "source": payload.get("source", "multi-platform assignment listing"),
        "last_scan_at": payload.get("last_scan_at"),
        "scan_date": payload.get("scan_date"),
        "sources": sources,
        "total_visible": sum(source["total_visible"] for source in sources.values()),
        "total_unique_visible": sum(
            source["total_unique_visible"] for source in sources.values()
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
    normalized_previous = normalize_memory_payload(previous_memory or {})
    sources = {
        source_key: dict(state)
        for source_key, state in normalized_previous.get("sources", {}).items()
    }
    for result in platform_results:
        if result.status != "ok" or result.platform not in SOURCE_REGISTRY:
            continue
        seen_ids = sorted(
            {assignment.source_id for assignment in assignments if assignment.source_key == result.platform}
        )
        sources[result.platform] = {
            "prefix": SOURCE_REGISTRY[result.platform]["prefix"],
            "seen_ids": seen_ids,
            "total_visible": result.count,
            "total_unique_visible": len(seen_ids),
        }

    return {
        "source": "multi-platform assignment listing",
        "last_scan_at": now,
        "scan_date": scan_date.isoformat(),
        "sources": {source_key: sources.get(source_key, _default_source_entry(source_key)) for source_key in SOURCE_REGISTRY},
        "total_visible": sum(
            state.get("total_visible", 0) for state in sources.values()
        ),
        "total_unique_visible": sum(
            state.get("total_unique_visible", 0) for state in sources.values()
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
