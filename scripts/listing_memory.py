"""Persistent dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import AssignmentRecord, PlatformScanResult

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEMORY_PATH = REPO_ROOT / "assignment-listing-seen.json"


def collect_seen_keys(data: dict[str, Any]) -> set[str]:
    """Read seen dedupe keys from current or legacy memory shapes."""
    seen_keys: set[str] = set()
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
    """Keep dedupe ids only in seen_keys; retain per-platform scan metadata."""
    seen_keys = collect_seen_keys(payload)
    platforms: dict[str, Any] = {}
    raw_platforms = payload.get("platforms")
    if isinstance(raw_platforms, dict):
        for platform_id, state in raw_platforms.items():
            if not isinstance(state, dict):
                continue
            entry: dict[str, Any] = {
                "status": state.get("status"),
                "total_visible": state.get("total_visible"),
            }
            if state.get("message"):
                entry["message"] = state["message"]
            platforms[platform_id] = entry

    normalized: dict[str, Any] = {
        "source": payload.get("source", "multi-platform assignment listing"),
        "last_scan_at": payload.get("last_scan_at"),
        "scan_date": payload.get("scan_date"),
        "platforms": platforms,
        "seen_keys": sorted(seen_keys),
        "total_visible": payload.get("total_visible", len(seen_keys)),
        "total_unique_visible": payload.get("total_unique_visible", len(seen_keys)),
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
    platforms: dict[str, Any] = {}
    for result in platform_results:
        platforms[result.platform] = {
            "status": result.status,
            "total_visible": result.count,
        }
        if result.message:
            platforms[result.platform]["message"] = result.message

    return {
        "source": "multi-platform assignment listing",
        "last_scan_at": now,
        "scan_date": scan_date.isoformat(),
        "platforms": platforms,
        "seen_keys": sorted({assignment.dedupe_key for assignment in assignments}),
        "total_visible": len(assignments),
        "total_unique_visible": len({assignment.dedupe_key for assignment in assignments}),
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
