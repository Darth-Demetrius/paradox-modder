from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .domain import ConflictEntry
from .project import WorkflowProject

TRACKING_STATE_FILE = "state.json"


TrackingState = dict[str, Any]


def load_tracking_state(project: WorkflowProject) -> TrackingState:
    path = project.tracking_dir / TRACKING_STATE_FILE
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_tracking_state(project: WorkflowProject, state: TrackingState) -> None:
    project.tracking_dir.mkdir(parents=True, exist_ok=True)
    path = project.tracking_dir / TRACKING_STATE_FILE
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def tracking_payload(entry: ConflictEntry) -> dict[str, Any]:
    return {
        "path": entry.output_rel,
        "record_type": entry.key.record_type,
        "source_path": entry.key.source_path,
        "name": entry.key.name,
        "sources": {
            source.ref: {
                "hash": source.source_hash,
                "sort_key": source.position,
                "supported_version": source.supported_version,
                "body": source.body,
            }
            for source in entry.sources
        },
    }


def determine_status(previous: dict[str, Any] | None, current: dict[str, Any], merged_exists: bool) -> str:
    previous_sources = previous.get("sources", {}) if isinstance(previous, dict) else {}
    current_sources = current["sources"]
    previous_refs = set(previous_sources)
    current_refs = set(current_sources)
    missing_refs = previous_refs - current_refs
    changed_refs = {
        ref for ref in previous_refs & current_refs if previous_sources[ref].get("hash") != current_sources[ref]["hash"]
    }
    new_refs = current_refs - previous_refs

    if merged_exists:
        if missing_refs:
            return "source-missing"
        if changed_refs:
            return "stale"
        if new_refs:
            return "new-upstream"
        return "up-to-date"

    if missing_refs or changed_refs or new_refs or not previous_sources:
        return "new-upstream"
    return "up-to-date"
