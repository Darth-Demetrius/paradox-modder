from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .domain import ConflictEntry, ConflictKey, ConflictSource, PREAMBLE_NAME, SnapshotRecord, WHOLE_FILE_NAME
from .layout import derive_output_from_refs, merged_path, snapshot_path, split_ref
from .metadata import render_metadata_block, split_file_sections
from .parse import iter_object_blocks
from .project import WorkflowProject
from .tracking import determine_status, load_tracking_state, tracking_payload


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def managed_roots(project: WorkflowProject) -> list[Path]:
    roots = [project.build_dir, project.merged_dir, project.conflicts_dir, project.patch_dir]
    roots.extend(project.root / mod_path for mod_path in project.alias_to_path.values() if mod_path)
    return roots


def iter_mod_text_files(project: WorkflowProject, mod_name: str) -> list[Path]:
    mod_dir = project.root / mod_name
    if mod_name:
        return sorted(mod_dir.rglob("*.txt"))

    excluded_roots = managed_roots(project)
    return [
        path
        for path in sorted(project.root.rglob("*.txt"))
        if not any(is_relative_to(path, root) for root in excluded_roots)
    ]


def read_mod_metadata(project: WorkflowProject, mod_name: str) -> dict[str, str]:
    mod_dir = project.root / mod_name
    descriptor = mod_dir / "descriptor.mod"
    metadata: dict[str, str] = {}
    if not descriptor.exists():
        return metadata
    for line in descriptor.read_text(encoding="utf-8").splitlines():
        match = project.descriptor_re.match(line)
        if match and match.group("key") in ("version", "supported_version"):
            metadata[match.group("key")] = match.group("value").strip().removeprefix("v").removeprefix("V")
    return metadata


def scan_sources(project: WorkflowProject) -> dict[ConflictKey, dict[str, ConflictSource]]:
    occurrences: dict[ConflictKey, dict[str, ConflictSource]] = defaultdict(dict)
    metadata_cache = {mod_name: read_mod_metadata(project, mod_name) for mod_name in project.mods_to_check}

    for mod_name in project.mods_to_check:
        mod_dir = project.root / mod_name
        for path in iter_mod_text_files(project, mod_name):
            ref = f"{mod_name}/{path.relative_to(mod_dir).as_posix()}"
            rel_path = path.relative_to(mod_dir).as_posix()
            text = path.read_text(encoding="utf-8")
            supported_version = metadata_cache[mod_name].get("supported_version", "")
            object_blocks = iter_object_blocks(text, project.object_start_re)
            preamble, _, _ = split_file_sections(text, project.object_start_re)

            if object_blocks:
                if preamble.strip():
                    occurrences[ConflictKey(rel_path, PREAMBLE_NAME, "preamble")][ref] = ConflictSource(
                        ref=ref,
                        position=0,
                        source_hash=hash_text(preamble.rstrip()),
                        supported_version=supported_version,
                        body=preamble.rstrip(),
                    )
                for object_id, block, position in object_blocks:
                    occurrences[ConflictKey(rel_path, object_id, "object")][ref] = ConflictSource(
                        ref=ref,
                        position=position,
                        source_hash=hash_text(block),
                        supported_version=supported_version,
                        body=block,
                    )
                continue

            stripped = text.rstrip()
            if stripped:
                occurrences[ConflictKey(rel_path, WHOLE_FILE_NAME, "file")][ref] = ConflictSource(
                    ref=ref,
                    position=0,
                    source_hash=hash_text(stripped),
                    supported_version=supported_version,
                    body=stripped,
                )
    return occurrences


def is_conflict(project: WorkflowProject, key: ConflictKey, refs_by_ref: dict[str, ConflictSource]) -> bool:
    mods = {split_ref(project, ref)[0] for ref in refs_by_ref}
    if len(mods) <= 1:
        return False
    aliases = {project.path_to_alias.get(mod_name, mod_name.lower()) for mod_name in mods}
    if not aliases.intersection(project.conflict_filter_source_mods):
        return False
    if key.record_type in {"preamble", "file"}:
        return len({source.source_hash for source in refs_by_ref.values()}) > 1
    return True


def collect_conflicts(project: WorkflowProject) -> tuple[list[ConflictEntry], dict[str, Any]]:
    previous_state = load_tracking_state(project)
    current_state: dict[str, Any] = {}
    conflicts: list[ConflictEntry] = []

    for key, refs_by_ref in sorted(
        scan_sources(project).items(),
        key=lambda item: (item[0].source_path, item[0].record_type, item[0].name),
    ):
        if not is_conflict(project, key, refs_by_ref):
            continue
        sources = tuple(refs_by_ref[ref] for ref in sorted(refs_by_ref))
        output_rel = derive_output_from_refs(project, [source.ref for source in sources])
        record = {
            "output": output_rel,
            "record_type": key.record_type,
            "source_path": key.source_path,
            "name": key.name,
            "sources": {
                source.ref: {
                    "hash": source.source_hash,
                    "position": source.position,
                    "supported_version": source.supported_version,
                    "body": source.body,
                }
                for source in sources
            },
        }
        entry = ConflictEntry(
            key=key,
            output_rel=output_rel,
            merged_path=merged_path(project, output_rel, key),
            status=determine_status(previous_state.get(key.tracking_id), record, merged_path(project, output_rel, key).exists()),
            sources=sources,
        )
        current_state[key.tracking_id] = tracking_payload(entry)
        conflicts.append(entry)
    return conflicts, current_state


def write_conflicts(project: WorkflowProject, conflicts: list[ConflictEntry]) -> None:
    project.conflicts_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, int] = defaultdict(int)
    items: list[dict[str, Any]] = []
    for entry in conflicts:
        summary[entry.status] += 1
        items.append(
            {
                "record_type": entry.key.record_type,
                "source_path": entry.key.source_path,
                "name": entry.key.name,
                "output": entry.output_rel,
                "merged_file": entry.merged_path.relative_to(project.root).as_posix(),
                "status": entry.status,
                "sources": [
                    {
                        "ref": source.ref,
                        "position": source.position,
                        "hash": source.source_hash,
                        "supported_version": source.supported_version,
                    }
                    for source in entry.sources
                ],
            }
        )
    path = project.conflicts_dir / "conflicts.json"
    path.write_text(
        json.dumps({"summary": {"total": len(conflicts), **dict(sorted(summary.items()))}, "items": items}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote: {path.relative_to(project.root)}")
    print(f"summary: {len(conflicts)} conflicts")


def build_sort_key(project: WorkflowProject, name: str, ref: str, position: int) -> tuple[int, int, str]:
    mod_name, _ = split_ref(project, ref)
    alias = project.path_to_alias.get(mod_name, mod_name.lower())
    return (project.mod_priority.get(alias, len(project.mod_priority)), position, name)


def snapshot_conflicts(project: WorkflowProject, conflicts: list[ConflictEntry]) -> dict[ConflictKey, dict[str, SnapshotRecord]]:
    snapshots: dict[ConflictKey, dict[str, SnapshotRecord]] = defaultdict(dict)
    count = 0
    for entry in conflicts:
        for source in entry.sources:
            mod_name, _ = split_ref(project, source.ref)
            out = snapshot_path(project, source.ref, entry.key)
            out.parent.mkdir(parents=True, exist_ok=True)
            content = render_metadata_block(
                {
                    "record_type": entry.key.record_type,
                    "source_mod": project.path_to_alias.get(mod_name, mod_name.lower()),
                    "source_path": entry.key.source_path,
                    "supported_version": source.supported_version,
                    "position": source.position,
                },
                metadata_line_template=project.metadata_line_template,
            ) + source.body
            out.write_text(content + "\n", encoding="utf-8")
            snapshots[entry.key][source.ref] = SnapshotRecord(
                metadata={"supported_version": source.supported_version},
                body=source.body,
                position=source.position,
                source_hash=source.source_hash,
            )
            count += 1
    print(f"snapshot: {count} records")
    return snapshots


def seed_conflicts(project: WorkflowProject, conflicts: list[ConflictEntry], snapshots: dict[ConflictKey, dict[str, SnapshotRecord]]) -> None:
    created = skipped = 0
    for entry in conflicts:
        if entry.merged_path.exists():
            skipped += 1
            continue
        primary_source = min(
            entry.sources,
            key=lambda source: (build_sort_key(project, entry.key.name, source.ref, source.position), source.ref),
        )
        metadata: dict[str, object] = {
            "output": entry.output_rel,
            "record_type": entry.key.record_type,
            "name": entry.key.name,
            "source_path": entry.key.source_path,
            "upstream_status": entry.status,
            "sort_key": build_sort_key(project, entry.key.name, primary_source.ref, primary_source.position),
            "sources": [
                {"ref": source.ref, "supported_version": source.supported_version}
                for source in entry.sources
            ],
        }
        entry.merged_path.parent.mkdir(parents=True, exist_ok=True)
        entry.merged_path.write_text(
            render_metadata_block(
                metadata,
                metadata_line_template=project.metadata_line_template,
                include_auto_generated=True,
            )
            + snapshots[entry.key][primary_source.ref].body
            + "\n",
            encoding="utf-8",
        )
        print(f"seeded: {entry.merged_path.relative_to(project.root)}")
        created += 1
    print(f"seed: {created} created, {skipped} skipped")
