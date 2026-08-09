"""Persistent dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import AssignmentRecord, PLATFORM_PREFIXES, PlatformScanResult

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


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize current and legacy payloads into the per-source memory shape."""
    seen_keys = collect_seen_keys(payload)
    source_states: dict[str, dict[str, Any]] = {}

    raw_sources = payload.get("sources")
    if isinstance(raw_sources, dict):
        for source_key, state in raw_sources.items():
            if not isinstance(state, dict):
                continue
            seen_ids = [str(item) for item in state.get("seen_ids", [])]
            source_states[source_key] = {
                "prefix": state.get("prefix") or PLATFORM_PREFIXES.get(source_key, ""),
                "seen_ids": sorted(set(seen_ids), key=lambda item: (len(item), item)),
                "total_visible": int(state.get("total_visible") or len(seen_ids)),
                "total_unique_visible": int(
                    state.get("total_unique_visible") or len(set(seen_ids))
                ),
            }

    raw_platforms = payload.get("platforms")
    if isinstance(raw_platforms, dict):
        for source_key, state in raw_platforms.items():
            if not isinstance(state, dict):
                continue
            source_states.setdefault(
                source_key,
                {
                    "prefix": PLATFORM_PREFIXES.get(source_key, ""),
                    "seen_ids": sorted(
                        {
                            key.split(":", 1)[1]
                            for key in seen_keys
                            if key.startswith(f"{source_key}:")
                        },
                        key=lambda item: (len(item), item),
                    ),
                    "total_visible": int(state.get("total_visible") or 0),
                    "total_unique_visible": int(state.get("total_unique_visible") or 0),
                },
            )

    for key in sorted(seen_keys):
        if ":" not in key:
            continue
        source_key, source_id = key.split(":", 1)
        state = source_states.setdefault(
            source_key,
            {
                "prefix": PLATFORM_PREFIXES.get(source_key, ""),
                "seen_ids": [],
                "total_visible": 0,
                "total_unique_visible": 0,
            },
        )
        if source_id not in state["seen_ids"]:
            state["seen_ids"].append(source_id)

    for state in source_states.values():
        state["seen_ids"] = sorted(set(state["seen_ids"]), key=lambda item: (len(item), item))
        if not state.get("total_visible"):
            state["total_visible"] = len(state["seen_ids"])
        if not state.get("total_unique_visible"):
            state["total_unique_visible"] = len(state["seen_ids"])

    normalized: dict[str, Any] = {
        "last_scan_at": payload.get("last_scan_at"),
        "scan_date": payload.get("scan_date"),
        "sources": source_states,
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
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    sources: dict[str, Any] = {}
    successful_sources = {result.platform for result in platform_results if result.status == "ok"}
    for source_key in successful_sources:
        source_ids = sorted(
            {
                assignment.source_id
                for assignment in assignments
                if assignment.platform == source_key
            },
            key=lambda item: (len(item), item),
        )
        sources[source_key] = {
            "prefix": PLATFORM_PREFIXES.get(source_key, ""),
            "seen_ids": source_ids,
            "total_visible": next(
                (result.count for result in platform_results if result.platform == source_key),
                len(source_ids),
            ),
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
    existing: dict[str, Any] = {}
    if memory_path.is_file() and memory_path.stat().st_size:
        try:
            existing = json.loads(memory_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
    merged = normalize_memory_payload(existing)
    update = normalize_memory_payload(memory_update)
    merged["last_scan_at"] = update.get("last_scan_at")
    merged["scan_date"] = update.get("scan_date")
    merged.setdefault("sources", {}).update(update.get("sources", {}))
    write_memory_file(memory_path, merged)


def read_memory_export(memory_path: Path) -> str:
    if not memory_path.is_file() or memory_path.stat().st_size == 0:
        return ""
    return memory_path.read_text(encoding="utf-8")
