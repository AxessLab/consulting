"""Persistent dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import AssignmentRecord, DEFAULT_PLATFORMS, PLATFORM_PREFIXES, PlatformScanResult

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


def _source_state_from_seen_keys(seen_keys: set[str]) -> dict[str, dict[str, Any]]:
    sources: dict[str, dict[str, Any]] = {}
    for platform_id in DEFAULT_PLATFORMS:
        sources[platform_id] = {
            "prefix": PLATFORM_PREFIXES[platform_id],
            "seen_ids": [],
            "total_visible": 0,
            "total_unique_visible": 0,
        }

    for seen_key in seen_keys:
        if ":" not in seen_key:
            continue
        platform_id, source_id = seen_key.split(":", 1)
        entry = sources.setdefault(
            platform_id,
            {
                "prefix": PLATFORM_PREFIXES.get(platform_id, ""),
                "seen_ids": [],
                "total_visible": 0,
                "total_unique_visible": 0,
            },
        )
        entry["seen_ids"].append(source_id)

    for entry in sources.values():
        entry["seen_ids"] = sorted(set(str(item) for item in entry["seen_ids"]))
        if not entry.get("total_visible"):
            entry["total_visible"] = len(entry["seen_ids"])
        if not entry.get("total_unique_visible"):
            entry["total_unique_visible"] = len(entry["seen_ids"])
    return sources


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize current and legacy memory shapes into the per-source schema."""
    seen_keys = collect_seen_keys(payload)
    sources = _source_state_from_seen_keys(seen_keys)

    raw_sources = payload.get("sources")
    if isinstance(raw_sources, dict):
        for source_key, state in raw_sources.items():
            if not isinstance(state, dict):
                continue
            seen_ids = [str(item) for item in state.get("seen_ids", [])] if isinstance(state.get("seen_ids"), list) else []
            entry = sources.setdefault(
                source_key,
                {
                    "prefix": state.get("prefix") or PLATFORM_PREFIXES.get(source_key, ""),
                    "seen_ids": [],
                    "total_visible": 0,
                    "total_unique_visible": 0,
                },
            )
            entry["prefix"] = state.get("prefix") or entry.get("prefix") or PLATFORM_PREFIXES.get(source_key, "")
            entry["seen_ids"] = sorted(set(seen_ids or entry.get("seen_ids", [])))
            entry["total_visible"] = state.get("total_visible", len(entry["seen_ids"]))
            entry["total_unique_visible"] = state.get("total_unique_visible", len(entry["seen_ids"]))
            if state.get("message"):
                entry["message"] = state["message"]

    raw_platforms = payload.get("platforms")
    if isinstance(raw_platforms, dict):
        for source_key, state in raw_platforms.items():
            if not isinstance(state, dict):
                continue
            entry = sources.setdefault(
                source_key,
                {
                    "prefix": PLATFORM_PREFIXES.get(source_key, ""),
                    "seen_ids": [],
                    "total_visible": 0,
                    "total_unique_visible": 0,
                },
            )
            if state.get("total_visible") is not None:
                entry["total_visible"] = state["total_visible"]
            if state.get("total_unique_visible") is not None:
                entry["total_unique_visible"] = state["total_unique_visible"]
            elif state.get("total_visible") is not None:
                entry["total_unique_visible"] = state["total_visible"]
            if state.get("message"):
                entry["message"] = state["message"]

    normalized: dict[str, Any] = {
        "source": payload.get("source", "multi-platform assignment listing"),
        "last_scan_at": payload.get("last_scan_at"),
        "scan_date": payload.get("scan_date"),
        "sources": sources,
        "total_visible": payload.get(
            "total_visible",
            sum(int(state.get("total_visible") or 0) for state in sources.values()),
        ),
        "total_unique_visible": payload.get(
            "total_unique_visible",
            sum(int(state.get("total_unique_visible") or 0) for state in sources.values()),
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
    existing_memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    existing_sources = normalize_memory_payload(existing_memory or {}).get("sources", {})
    sources: dict[str, Any] = {
        platform_id: {
            "prefix": PLATFORM_PREFIXES[platform_id],
            "seen_ids": list((existing_sources.get(platform_id) or {}).get("seen_ids", [])),
            "total_visible": (existing_sources.get(platform_id) or {}).get("total_visible", 0),
            "total_unique_visible": (existing_sources.get(platform_id) or {}).get(
                "total_unique_visible",
                (existing_sources.get(platform_id) or {}).get("total_visible", 0),
            ),
        }
        for platform_id in DEFAULT_PLATFORMS
    }
    ids_by_platform: dict[str, set[str]] = {}
    for assignment in assignments:
        ids_by_platform.setdefault(assignment.platform, set()).add(assignment.source_id)

    for result in platform_results:
        entry = sources.setdefault(
            result.platform,
            {
                "prefix": PLATFORM_PREFIXES.get(result.platform, ""),
                "seen_ids": [],
                "total_visible": 0,
                "total_unique_visible": 0,
            },
        )
        if result.status == "ok":
            visible_ids = sorted(ids_by_platform.get(result.platform, set()))
            entry["seen_ids"] = visible_ids
            entry["total_visible"] = result.count
            entry["total_unique_visible"] = len(visible_ids)
        if result.message:
            entry["message"] = result.message

    return {
        "source": "multi-platform assignment listing",
        "last_scan_at": now,
        "scan_date": scan_date.isoformat(),
        "sources": sources,
        "total_visible": sum(
            int(state.get("total_visible") or 0) for state in sources.values()
        ),
        "total_unique_visible": sum(
            int(state.get("total_unique_visible") or 0) for state in sources.values()
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
