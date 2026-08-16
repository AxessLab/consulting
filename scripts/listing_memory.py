"""Persistent dedupe memory for assignment listing runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from assignment_platforms import (
    DEFAULT_PLATFORMS,
    SOURCE_PREFIXES,
    AssignmentRecord,
    PlatformScanResult,
)

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
    """Normalize current and legacy memory into per-source bare seen ids."""
    seen_keys = collect_seen_keys(payload)
    sources: dict[str, Any] = {}
    raw_sources = payload.get("sources")
    raw_platforms = payload.get("platforms")
    source_keys: list[str] = list(DEFAULT_PLATFORMS)
    if isinstance(raw_sources, dict):
        source_keys.extend(str(key) for key in raw_sources if key not in source_keys)
    if isinstance(raw_platforms, dict):
        source_keys.extend(str(key) for key in raw_platforms if key not in source_keys)
    for key in sorted(
        {item for item in source_keys if item},
        key=lambda item: source_keys.index(item) if item in source_keys else 999,
    ):
        raw_state = raw_sources.get(key, {}) if isinstance(raw_sources, dict) else {}
        legacy_state = raw_platforms.get(key, {}) if isinstance(raw_platforms, dict) else {}
        source_seen = sorted(
            dedupe_key.split(":", 1)[1]
            for dedupe_key in seen_keys
            if dedupe_key.startswith(f"{key}:")
        )
        if not source_seen and isinstance(raw_state, dict) and isinstance(
            raw_state.get("seen_ids"), list
        ):
            source_seen = sorted(str(item) for item in raw_state["seen_ids"])

        total_visible = None
        total_unique_visible = None
        if isinstance(raw_state, dict):
            total_visible = raw_state.get("total_visible")
            total_unique_visible = raw_state.get("total_unique_visible")
        if total_visible is None and isinstance(legacy_state, dict):
            total_visible = legacy_state.get("total_visible")
        if total_unique_visible is None:
            total_unique_visible = len(source_seen)

        sources[key] = {
            "prefix": (
                raw_state.get("prefix")
                if isinstance(raw_state, dict) and raw_state.get("prefix")
                else SOURCE_PREFIXES.get(key, "")
            ),
            "seen_ids": source_seen,
            "total_visible": total_visible if total_visible is not None else len(source_seen),
            "total_unique_visible": total_unique_visible,
        }

    # Migrate legacy single-source memory into the allakonsultuppdrag source.
    legacy_seen = payload.get("seen_ids")
    if isinstance(legacy_seen, list):
        state = sources.setdefault(
            "allakonsultuppdrag.se",
            {
                "prefix": SOURCE_PREFIXES["allakonsultuppdrag.se"],
                "seen_ids": [],
                "total_visible": 0,
                "total_unique_visible": 0,
            },
        )
        merged = sorted({*state["seen_ids"], *(str(item) for item in legacy_seen)})
        state["seen_ids"] = merged
        state["total_visible"] = max(int(state.get("total_visible") or 0), len(merged))
        state["total_unique_visible"] = max(
            int(state.get("total_unique_visible") or 0), len(merged)
        )

    total_visible = sum(int(state.get("total_visible") or 0) for state in sources.values())
    total_unique_visible = sum(
        int(state.get("total_unique_visible") or 0) for state in sources.values()
    )

    normalized: dict[str, Any] = {
        "source": payload.get("source", "multi-source assignment listing"),
        "last_scan_at": payload.get("last_scan_at"),
        "scan_date": payload.get("scan_date"),
        "sources": sources,
        "total_visible": payload.get("total_visible", total_visible),
        "total_unique_visible": payload.get("total_unique_visible", total_unique_visible),
    }
    return normalized


def _initial_sources_from_previous(previous_memory: dict[str, Any] | None) -> dict[str, Any]:
    previous = normalize_memory_payload(previous_memory or {})
    raw_sources = previous.get("sources")
    if not isinstance(raw_sources, dict):
        raw_sources = {}
    sources: dict[str, Any] = {}
    for source_key in DEFAULT_PLATFORMS:
        state = raw_sources.get(source_key, {})
        if not isinstance(state, dict):
            state = {}
        seen_ids = state.get("seen_ids") if isinstance(state.get("seen_ids"), list) else []
        sources[source_key] = {
            "prefix": state.get("prefix") or SOURCE_PREFIXES.get(source_key, ""),
            "seen_ids": [str(item) for item in seen_ids],
            "total_visible": int(state.get("total_visible") or 0),
            "total_unique_visible": int(state.get("total_unique_visible") or len(seen_ids)),
        }
    for source_key, state in raw_sources.items():
        if source_key in sources or not isinstance(state, dict):
            continue
        seen_ids = state.get("seen_ids") if isinstance(state.get("seen_ids"), list) else []
        sources[source_key] = {
            "prefix": state.get("prefix") or SOURCE_PREFIXES.get(source_key, ""),
            "seen_ids": [str(item) for item in seen_ids],
            "total_visible": int(state.get("total_visible") or 0),
            "total_unique_visible": int(state.get("total_unique_visible") or len(seen_ids)),
        }
    return sources


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
    sources = _initial_sources_from_previous(previous_memory)
    ids_by_source: dict[str, set[str]] = {}
    for assignment in assignments:
        ids_by_source.setdefault(assignment.platform, set()).add(str(assignment.source_id))

    for result in platform_results:
        if result.status != "ok":
            continue
        seen_ids = sorted(ids_by_source.get(result.platform, set()))
        sources[result.platform] = {
            "prefix": SOURCE_PREFIXES.get(result.platform, ""),
            "seen_ids": seen_ids,
            "total_visible": result.count,
            "total_unique_visible": len(seen_ids),
        }

    total_visible = sum(int(state.get("total_visible") or 0) for state in sources.values())
    total_unique_visible = sum(
        int(state.get("total_unique_visible") or 0) for state in sources.values()
    )

    return {
        "source": "multi-source assignment listing",
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
