"""Persistent dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import AssignmentRecord, PlatformScanResult

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEMORY_PATH = REPO_ROOT / "assignment-listing-seen.json"

SOURCE_PREFIXES = {
    "allakonsultuppdrag.se": "a",
    "verama.com": "v",
    "chaspartnernetwork.se": "c",
    "magnit-source.magnitglobal.com": "m",
    "cinode.com/market": "n",
}
SOURCE_ORDER = tuple(SOURCE_PREFIXES)


def _sorted_ids(values: set[str]) -> list[str]:
    return sorted(values, key=lambda value: (not value.isdigit(), value))


def collect_seen_ids_by_source(data: dict[str, Any]) -> dict[str, set[str]]:
    """Read source-scoped seen ids from current and legacy memory shapes."""
    seen_by_source: dict[str, set[str]] = {}

    sources = data.get("sources")
    if isinstance(sources, dict):
        for source_key, state in sources.items():
            if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
                seen_by_source.setdefault(source_key, set()).update(
                    str(item) for item in state["seen_ids"]
                )

    if isinstance(data.get("seen_keys"), list):
        for item in data["seen_keys"]:
            text = str(item)
            if ":" not in text:
                continue
            source_key, source_id = text.split(":", 1)
            if source_key and source_id:
                seen_by_source.setdefault(source_key, set()).add(source_id)

    platforms = data.get("platforms")
    if isinstance(platforms, dict):
        for platform_id, state in platforms.items():
            if isinstance(state, dict) and isinstance(state.get("seen_ids"), list):
                seen_by_source.setdefault(platform_id, set()).update(
                    str(source_id) for source_id in state["seen_ids"]
                )

    legacy_seen = data.get("seen_ids")
    if isinstance(legacy_seen, list):
        seen_by_source.setdefault("allakonsultuppdrag.se", set()).update(
            str(source_id) for source_id in legacy_seen
        )

    return seen_by_source


def collect_seen_keys(data: dict[str, Any]) -> set[str]:
    """Read seen dedupe keys from current or legacy memory shapes."""
    seen_keys: set[str] = set()
    for source_key, seen_ids in collect_seen_ids_by_source(data).items():
        for source_id in seen_ids:
            seen_keys.add(f"{source_key}:{source_id}")

    return seen_keys


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize memory to the source-scoped shape used by cloud automation."""
    seen_by_source = collect_seen_ids_by_source(payload)
    raw_sources = payload.get("sources") if isinstance(payload.get("sources"), dict) else {}
    raw_platforms = (
        payload.get("platforms") if isinstance(payload.get("platforms"), dict) else {}
    )

    source_keys = list(SOURCE_ORDER)
    for source_key in sorted(set(seen_by_source) | set(raw_sources) | set(raw_platforms)):
        if source_key not in source_keys:
            source_keys.append(source_key)

    sources: dict[str, Any] = {}
    for source_key in source_keys:
        source_state = raw_sources.get(source_key) if isinstance(raw_sources, dict) else None
        platform_state = (
            raw_platforms.get(source_key) if isinstance(raw_platforms, dict) else None
        )
        state = source_state if isinstance(source_state, dict) else {}
        fallback_state = platform_state if isinstance(platform_state, dict) else {}
        seen_ids = _sorted_ids(seen_by_source.get(source_key, set()))
        total_visible = state.get("total_visible", fallback_state.get("total_visible", 0))
        total_unique_visible = state.get(
            "total_unique_visible",
            fallback_state.get("total_unique_visible", len(seen_ids)),
        )
        sources[source_key] = {
            "prefix": str(state.get("prefix") or SOURCE_PREFIXES.get(source_key, "")),
            "seen_ids": seen_ids,
            "total_visible": int(total_visible or 0),
            "total_unique_visible": int(total_unique_visible or 0),
        }

    normalized: dict[str, Any] = {
        "source": payload.get("source", "multi-platform assignment listing"),
        "last_scan_at": payload.get("last_scan_at"),
        "scan_date": payload.get("scan_date"),
        "sources": sources,
        "total_visible": int(
            payload.get(
                "total_visible",
                sum(source["total_visible"] for source in sources.values()),
            )
            or 0
        ),
        "total_unique_visible": int(
            payload.get(
                "total_unique_visible",
                sum(source["total_unique_visible"] for source in sources.values()),
            )
            or 0
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
    previous = normalize_memory_payload(previous_memory or {})
    previous_sources = previous.get("sources") if isinstance(previous.get("sources"), dict) else {}

    successful_sources = {result.platform for result in platform_results if result.status == "ok"}
    results_by_source = {result.platform: result for result in platform_results}
    visible_by_source: dict[str, set[str]] = {}
    for assignment in assignments:
        if assignment.platform not in successful_sources:
            continue
        visible_by_source.setdefault(assignment.platform, set()).add(assignment.source_id)

    source_keys = list(SOURCE_ORDER)
    for source_key in sorted(set(results_by_source) | set(previous_sources) | set(visible_by_source)):
        if source_key not in source_keys:
            source_keys.append(source_key)

    sources: dict[str, Any] = {}
    for source_key in source_keys:
        previous_state = (
            previous_sources.get(source_key) if isinstance(previous_sources, dict) else None
        )
        result = results_by_source.get(source_key)
        if result and result.status == "ok":
            ids = _sorted_ids(visible_by_source.get(source_key, set()))
            sources[source_key] = {
                "prefix": SOURCE_PREFIXES.get(source_key, ""),
                "seen_ids": ids,
                "total_visible": result.count,
                "total_unique_visible": len(ids),
            }
        elif isinstance(previous_state, dict):
            sources[source_key] = previous_state
        else:
            sources[source_key] = {
                "prefix": SOURCE_PREFIXES.get(source_key, ""),
                "seen_ids": [],
                "total_visible": 0,
                "total_unique_visible": 0,
            }

    total_visible = sum(
        state["total_visible"]
        for source_key, state in sources.items()
        if (source_key in successful_sources)
    )
    total_unique_visible = sum(
        state["total_unique_visible"]
        for source_key, state in sources.items()
        if (source_key in successful_sources)
    )

    return {
        "source": "multi-platform assignment listing",
        "last_scan_at": now,
        "scan_date": scan_date.isoformat(),
        "sources": sources,
        "total_visible": total_visible,
        "total_unique_visible": total_unique_visible,
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
