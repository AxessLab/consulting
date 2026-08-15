"""Persistent dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import SOURCE_REGISTRY, AssignmentRecord, PlatformScanResult

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


def collect_source_seen_ids(data: dict[str, Any]) -> dict[str, set[str]]:
    """Return bare source ids by source key from current or legacy memory."""
    by_source: dict[str, set[str]] = {
        source_key: set() for source_key in SOURCE_REGISTRY
    }
    sources = data.get("sources")
    if isinstance(sources, dict):
        for source_key, state in sources.items():
            if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
                by_source.setdefault(source_key, set()).update(
                    str(source_id) for source_id in state["seen_ids"]
                )

    platforms = data.get("platforms")
    if isinstance(platforms, dict):
        for source_key, state in platforms.items():
            if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
                by_source.setdefault(source_key, set()).update(
                    str(source_id) for source_id in state["seen_ids"]
                )

    for key in data.get("seen_keys") or []:
        if not isinstance(key, str) or ":" not in key:
            continue
        source_key, source_id = key.split(":", 1)
        by_source.setdefault(source_key, set()).add(source_id)

    legacy_seen = data.get("seen_ids")
    if isinstance(legacy_seen, list):
        by_source.setdefault("allakonsultuppdrag.se", set()).update(
            str(source_id) for source_id in legacy_seen
        )

    return by_source


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize memory to the unified source-scoped shape."""
    by_source = collect_source_seen_ids(payload)
    raw_sources = payload.get("sources") if isinstance(payload.get("sources"), dict) else {}
    raw_platforms = payload.get("platforms") if isinstance(payload.get("platforms"), dict) else {}

    sources: dict[str, Any] = {}
    for source_key, config in SOURCE_REGISTRY.items():
        old_state = {}
        if isinstance(raw_sources, dict) and isinstance(raw_sources.get(source_key), dict):
            old_state = raw_sources[source_key]
        elif isinstance(raw_platforms, dict) and isinstance(raw_platforms.get(source_key), dict):
            old_state = raw_platforms[source_key]

        seen_ids = sorted(by_source.get(source_key, set()), key=lambda item: (len(item), item))
        sources[source_key] = {
            "prefix": config["prefix"],
            "seen_ids": seen_ids,
            "total_visible": int(old_state.get("total_visible") or len(seen_ids)),
            "total_unique_visible": int(old_state.get("total_unique_visible") or len(seen_ids)),
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


def source_seen_ids(data: dict[str, Any]) -> dict[str, set[str]]:
    return collect_source_seen_ids(data)


def build_memory_payload(
    *,
    assignments: list[AssignmentRecord],
    platform_results: list[PlatformScanResult],
    scan_date: date,
    previous_memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    previous = normalize_memory_payload(previous_memory or {})
    previous_sources = previous.get("sources") if isinstance(previous.get("sources"), dict) else {}
    sources: dict[str, Any] = {
        source_key: {
            "prefix": config["prefix"],
            "seen_ids": [],
            "total_visible": 0,
            "total_unique_visible": 0,
        }
        for source_key, config in SOURCE_REGISTRY.items()
    }
    for source_key, state in previous_sources.items():
        if isinstance(state, dict):
            sources[source_key] = {
                "prefix": state.get("prefix") or SOURCE_REGISTRY.get(source_key, {}).get("prefix", ""),
                "seen_ids": [str(source_id) for source_id in state.get("seen_ids", [])],
                "total_visible": int(state.get("total_visible") or 0),
                "total_unique_visible": int(state.get("total_unique_visible") or 0),
            }

    assignments_by_source: dict[str, set[str]] = {}
    for assignment in assignments:
        assignments_by_source.setdefault(assignment.platform, set()).add(assignment.source_id)

    for result in platform_results:
        if result.status != "ok":
            continue
        seen_ids = sorted(
            assignments_by_source.get(result.platform, set()),
            key=lambda item: (len(item), item),
        )
        sources[result.platform] = {
            "prefix": SOURCE_REGISTRY.get(result.platform, {}).get("prefix", ""),
            "seen_ids": seen_ids,
            "total_visible": result.count,
            "total_unique_visible": len(seen_ids),
        }

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
