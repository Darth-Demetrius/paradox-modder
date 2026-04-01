from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any

from .domain import ConflictEntry, ConflictKey, ConflictSource, PREAMBLE_NAME, SnapshotRecord, WHOLE_FILE_NAME
from .layout import derive_output_from_refs, merged_path, snapshot_path, split_ref
from .metadata import render_metadata_block, split_file_sections
from .parse import collect_file_variable_definitions, iter_object_blocks, prepend_used_file_variables
from .project import WorkflowProject
from .tracking import determine_status, load_tracking_state, tracking_payload


IGNORED_CONFLICT_PATH_PARTS = {"events", "on_actions"}
IGNORED_CONFLICT_OBJECT_NAMES = {"inline_script"}
IGNORED_CONFLICT_OBJECT_PREFIXES = {"triggered_"}


def _debug_scan_enabled() -> bool:
    return os.getenv("PMMT_DEBUG_SCAN", "").strip().lower() in {"1", "true", "yes", "on"}


def _debug_filter_text() -> str:
    return os.getenv("PMMT_DEBUG_FILTER", "").strip().lower()


def _debug_key_match(key: ConflictKey) -> bool:
    filter_text = _debug_filter_text()
    if not filter_text:
        return True
    haystack = f"{key.tracking_id} {key.source_path} {key.name}".lower()
    return filter_text in haystack


def _debug_log(message: str) -> None:
    if _debug_scan_enabled():
        print(f"debug-scan: {message}")


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def managed_roots(project: WorkflowProject) -> list[Path]:
    return [project.build_dir, project.merged_dir, project.conflicts_dir, project.my_mod_dir]


def object_scope_path(rel_path: str) -> str:
    parent = Path(rel_path).parent.as_posix()
    return "" if parent == "." else parent


def normalize_conflict_source_path(project: WorkflowProject, source_path: str) -> str:
    raw = source_path.strip()
    if not raw:
        return raw
    candidate = Path(raw)
    if candidate.is_absolute():
        try:
            return candidate.relative_to(project.root).as_posix()
        except ValueError:
            return raw
    return candidate.as_posix()


def should_ignore_conflict_path(source_path: str) -> bool:
    return any(part in IGNORED_CONFLICT_PATH_PARTS for part in Path(source_path).parts)


def should_ignore_conflict_object(key: ConflictKey) -> bool:
    if key.record_type != "object":
        return False
    normalized_name = key.name.lower()
    if normalized_name in IGNORED_CONFLICT_OBJECT_NAMES:
        # TODO: Handle inline_script object merging once object-aware assembly logic exists.
        return True
    if any(normalized_name.startswith(prefix) for prefix in IGNORED_CONFLICT_OBJECT_PREFIXES):
        # TODO: Handle triggered_* object merging once object-aware assembly logic exists.
        return True
    return False


def iter_mod_text_files(project: WorkflowProject, mod_name: str, include_rel_paths: set[str] | None = None) -> list[Path]:
    mod_dir = project.root / mod_name
    if include_rel_paths is not None:
        excluded_roots = managed_roots(project) if not mod_name else []
        selected: list[Path] = []
        for rel_text in sorted(include_rel_paths):
            rel_path = Path(rel_text)
            path = mod_dir / rel_path
            if not path.is_file() or path.suffix != ".txt":
                continue
            if excluded_roots and any(is_relative_to(path, root) for root in excluded_roots):
                continue
            selected.append(path)
        return selected

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

    if _debug_scan_enabled():
        mods_list = ", ".join(project.mods_to_check)
        _debug_log(f"scanning mods: {mods_list}")

    def collect_from_mod(mod_name: str) -> None:
        mod_dir = project.root / mod_name
        if _debug_scan_enabled():
            _debug_log(f"scanning mod: {mod_name}")
            alias = project.path_to_alias.get(mod_name, mod_name.lower())
            _debug_log(f"  mod alias: {alias}")
        for path in iter_mod_text_files(project, mod_name):
            rel_path = path.relative_to(mod_dir).as_posix()
            alias = project.path_to_alias.get(mod_name, mod_name.lower())
            ref = f"{alias}/{rel_path}"
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            supported_version = metadata_cache[mod_name].get("supported_version", "")
            file_variable_definitions = collect_file_variable_definitions(text)
            try:
                object_blocks = iter_object_blocks(text, project.object_start_re)
            except Exception as e:
                # If parsing failed due to unbalanced braces, fall back to treating the
                # file as a whole-file (or preamble) so the scan can still detect
                # differences between mods for files you cannot edit (e.g. vanilla).
                msg = str(e)
                # print(msg, path)
                if msg.startswith("Unbalanced braces"):
                    preamble, _, _ = split_file_sections(text, project.object_start_re)
                    stripped = text.rstrip()
                    if preamble.strip():
                        normalized_preamble = preamble.rstrip().replace("    ", "\t")
                        occurrences[ConflictKey(rel_path, PREAMBLE_NAME, "preamble")][ref] = ConflictSource(
                            ref=ref,
                            position=0,
                            source_hash=hash_text(normalized_preamble),
                            supported_version=supported_version,
                            body=normalized_preamble,
                        )
                    elif stripped:
                        normalized_file = stripped.replace("    ", "\t")
                        occurrences[ConflictKey(rel_path, WHOLE_FILE_NAME, "file")][ref] = ConflictSource(
                            ref=ref,
                            position=0,
                            source_hash=hash_text(normalized_file),
                            supported_version=supported_version,
                            body=normalized_file,
                        )
                # For other parsing errors, skip the file as before.
                continue

            preamble, _, _ = split_file_sections(text, project.object_start_re)

            if object_blocks:
                if preamble.strip():
                    normalized_preamble = preamble.rstrip().replace("    ", "\t")
                    occurrences[ConflictKey(rel_path, PREAMBLE_NAME, "preamble")][ref] = ConflictSource(
                        ref=ref,
                        position=0,
                        source_hash=hash_text(normalized_preamble),
                        supported_version=supported_version,
                        body=normalized_preamble,
                    )
                for object_id, block, position in object_blocks:
                    normalized_block = block.replace("    ", "\t")
                    normalized_block = prepend_used_file_variables(normalized_block, file_variable_definitions)
                    key = ConflictKey(object_scope_path(rel_path), object_id, "object")
                    occurrences[key][ref] = ConflictSource(
                        ref=ref,
                        position=position,
                        source_hash=hash_text(normalized_block),
                        supported_version=supported_version,
                        body=normalized_block,
                    )
                    if _debug_scan_enabled() and _debug_key_match(key):
                        h = hash_text(normalized_block)[:12]
                        _debug_log(f"  found in {mod_name}: {key.tracking_id} hash={h} len={len(normalized_block)}")
                continue

            stripped = text.rstrip()
            if stripped:
                normalized_file = stripped.replace("    ", "\t")
                occurrences[ConflictKey(rel_path, WHOLE_FILE_NAME, "file")][ref] = ConflictSource(
                    ref=ref,
                    position=0,
                    source_hash=hash_text(normalized_file),
                    supported_version=supported_version,
                    body=normalized_file,
                )

    for mod_name in project.mods_to_check:
        collect_from_mod(mod_name)
    return occurrences


def is_conflict(project: WorkflowProject, key: ConflictKey, refs_by_ref: dict[str, ConflictSource]) -> bool:
    if should_ignore_conflict_path(key.source_path):
        if _debug_scan_enabled() and _debug_key_match(key):
            _debug_log(f"skip ignored path: {key.tracking_id}")
        return False
    if should_ignore_conflict_object(key):
        if _debug_scan_enabled() and _debug_key_match(key):
            _debug_log(f"skip ignored object: {key.tracking_id}")
        return False
    mods = {split_ref(project, ref)[0] for ref in refs_by_ref}
    if len(mods) <= 1:
        if _debug_scan_enabled() and _debug_key_match(key):
            _debug_log(f"skip single-mod key: {key.tracking_id} refs={sorted(refs_by_ref)}")
        return False
    aliases = {project.path_to_alias.get(mod_name, mod_name.lower()) for mod_name in mods}
    candidate_pairs = {
        frozenset((left, right))
        for left in aliases
        for right in aliases
        if left < right
    }
    if project.allowed_conflict_pairs and not candidate_pairs.intersection(project.allowed_conflict_pairs):
        if _debug_scan_enabled() and _debug_key_match(key):
            _debug_log(
                f"skip filtered pairs: {key.tracking_id} aliases={sorted(aliases)} allowed={sorted(tuple(p) for p in project.allowed_conflict_pairs)}"
            )
        return False
    different = len({source.source_hash for source in refs_by_ref.values()}) > 1
    if _debug_scan_enabled() and _debug_key_match(key):
        hashes = {ref: src.source_hash[:12] for ref, src in sorted(refs_by_ref.items())}
        _debug_log(f"key decision: {key.tracking_id} conflict={different} hashes={hashes}")
    return different


def collect_conflicts(project: WorkflowProject) -> tuple[list[ConflictEntry], dict[str, Any], dict[str, Any]]:
    previous_state = load_tracking_state(project)
    current_state: dict[str, Any] = {}
    conflicts: list[ConflictEntry] = []

    if _debug_scan_enabled():
        _debug_log(f"start scan: previous_state_entries={len(previous_state)}")

    for key, refs_by_ref in sorted(
        scan_sources(project).items(),
        key=lambda item: (item[0].source_path, item[0].record_type, item[0].name),
    ):
        normalized_key = ConflictKey(
            normalize_conflict_source_path(project, key.source_path),
            key.name,
            key.record_type,
        )
        if _debug_scan_enabled() and _debug_key_match(normalized_key):
            refs_debug = {
                ref: {
                    "hash": source.source_hash[:12],
                    "len": len(source.body),
                    "supported_version": source.supported_version,
                }
                for ref, source in sorted(refs_by_ref.items())
            }
            _debug_log(f"seen key: {normalized_key.tracking_id} refs={refs_debug}")
        if not is_conflict(project, key, refs_by_ref):
            continue
        sources = tuple(refs_by_ref[ref] for ref in sorted(refs_by_ref))
        output_rel = derive_output_from_refs(project, [source.ref for source in sources])
        record = {
            "path": output_rel,
            "record_type": normalized_key.record_type,
            "source_path": normalized_key.source_path,
            "name": normalized_key.name,
            "sources": {
                source.ref: {
                    "hash": source.source_hash,
                    "sort_key": build_sort_key(project, normalized_key.name, source.ref, source.position),
                    "supported_version": source.supported_version,
                    "body": source.body,
                }
                for source in sources
            },
        }
        entry = ConflictEntry(
            key=normalized_key,
            output_rel=output_rel,
            merged_path=merged_path(project, output_rel, normalized_key),
            status=determine_status(
                previous_state.get(normalized_key.tracking_id),
                record,
                merged_path(project, output_rel, normalized_key).exists(),
            ),
            sources=sources,
        )
        if _debug_scan_enabled() and _debug_key_match(normalized_key):
            previous = previous_state.get(normalized_key.tracking_id)
            previous_sources = previous.get("sources", {}) if isinstance(previous, dict) else {}
            current_sources = record["sources"]
            prev_refs = set(previous_sources)
            cur_refs = set(current_sources)
            changed_refs = sorted(
                ref
                for ref in (prev_refs & cur_refs)
                if previous_sources.get(ref, {}).get("hash") != current_sources[ref]["hash"]
            )
            _debug_log(
                "status details: "
                f"{normalized_key.tracking_id} status={entry.status} "
                f"new_refs={sorted(cur_refs - prev_refs)} "
                f"missing_refs={sorted(prev_refs - cur_refs)} "
                f"changed_refs={changed_refs}"
            )
        current_state[normalized_key.tracking_id] = tracking_payload(entry)
        conflicts.append(entry)

    if _debug_scan_enabled():
        _debug_log(f"end scan: current_conflicts={len(conflicts)} current_state_entries={len(current_state)}")
    return conflicts, current_state, previous_state


def _prune_empty_parents(path: Path, stop_at: Path) -> None:
    current = path
    while True:
        if current == stop_at or not current.exists() or not current.is_dir():
            return
        if any(current.iterdir()):
            return
        current.rmdir()
        current = current.parent


def cleanup_retired_conflicts(
    project: WorkflowProject,
    previous_state: dict[str, Any],
    current_state: dict[str, Any],
) -> None:
    retired_ids = set(previous_state) - set(current_state)
    removed_merged = 0
    removed_snapshots = 0

    for tracking_id in sorted(retired_ids):
        previous_record = previous_state.get(tracking_id)
        if not isinstance(previous_record, dict):
            continue

        output_rel = previous_record.get("path", "")
        record_type = previous_record.get("record_type", "")
        source_path = previous_record.get("source_path", "")
        name = previous_record.get("name", "")
        if not output_rel or not source_path or not name or record_type not in {"object", "preamble", "file"}:
            continue

        key = ConflictKey(source_path, name, record_type)
        merged = merged_path(project, output_rel, key)
        if merged.exists():
            merged.unlink()
            _prune_empty_parents(merged.parent, project.merged_dir)
            removed_merged += 1

        previous_sources = previous_record.get("sources", {})
        if not isinstance(previous_sources, dict):
            continue
        for ref in previous_sources:
            try:
                snap = snapshot_path(project, ref, key)
            except ValueError:
                continue
            if snap.exists():
                snap.unlink()
                _prune_empty_parents(snap.parent, project.tracking_dir)
                removed_snapshots += 1

    if removed_merged or removed_snapshots:
        print(f"cleanup: removed {removed_merged} merged records, {removed_snapshots} snapshots")


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
                "path": entry.output_rel,
                "merged_file": entry.merged_path.relative_to(project.root).as_posix(),
                "status": entry.status,
                "sources": [
                    {
                        "path": source.ref,
                        "sort_key": build_sort_key(project, entry.key.name, source.ref, source.position),
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


def snapshot_conflicts(
    project: WorkflowProject,
    conflicts: list[ConflictEntry]
) -> dict[ConflictKey, dict[str, SnapshotRecord]]:
    snapshots: dict[ConflictKey, dict[str, SnapshotRecord]] = defaultdict(dict)
    count = 0
    for entry in conflicts:
        for source in entry.sources:
            out = snapshot_path(project, source.ref, entry.key)
            out.parent.mkdir(parents=True, exist_ok=True)
            content = render_metadata_block(
                {
                    "record_type": entry.key.record_type,
                    "path": source.ref,
                    "supported_version": source.supported_version,
                    "sort_key": build_sort_key(project, entry.key.name, source.ref, source.position),
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


def seed_conflicts(
    project: WorkflowProject,
    conflicts: list[ConflictEntry],
    snapshots: dict[ConflictKey, dict[str, SnapshotRecord]]
    ) -> None:
    created = skipped = 0

    def build_sources_metadata(entry: ConflictEntry) -> list[dict[str, str]]:
        ordered_sources = sorted(entry.sources, key=lambda source: (source.ref, source.position))
        return [
            {"path": source.ref, "supported_version": source.supported_version}
            for source in ordered_sources
        ]

    def refresh_existing_merged_metadata(entry: ConflictEntry) -> bool:
        if not entry.merged_path.exists():
            return False
        text = entry.merged_path.read_text(encoding="utf-8")
        _, metadata, body = split_file_sections(text, project.object_start_re)
        if not metadata:
            return False
        refreshed_metadata: dict[str, object] = dict(metadata)
        refreshed_metadata.pop("name", None)
        refreshed_metadata.pop("upstream_status", None)
        refreshed_metadata.setdefault("supported_version", "")
        refreshed_metadata["sources"] = build_sources_metadata(entry)
        refreshed = (
            render_metadata_block(refreshed_metadata, metadata_line_template=project.metadata_line_template)
            + body
            + "\n"
        )
        if refreshed == text:
            return False
        entry.merged_path.write_text(refreshed, encoding="utf-8")
        print(f"updated: {entry.merged_path.relative_to(project.root)}")
        return True

    updated = 0
    for entry in conflicts:
        if entry.merged_path.exists():
            if refresh_existing_merged_metadata(entry):
                updated += 1
            skipped += 1
            continue
        primary_source = min(
            entry.sources,
            key=lambda source: (build_sort_key(project, entry.key.name, source.ref, source.position), source.ref),
        )
        metadata: dict[str, object] = {
            "record_type": entry.key.record_type,
            "path": entry.output_rel,
            "supported_version": "",
            "sort_key": build_sort_key(project, entry.key.name, primary_source.ref, primary_source.position),
            "sources": build_sources_metadata(entry),
        }
        entry.merged_path.parent.mkdir(parents=True, exist_ok=True)
        entry.merged_path.write_text(
            render_metadata_block(metadata, metadata_line_template=project.metadata_line_template)
            + snapshots[entry.key][primary_source.ref].body
            + "\n",
            encoding="utf-8",
        )
        print(f"seeded: {entry.merged_path.relative_to(project.root)}")
        created += 1
    print(f"seed: {created} created, {updated} updated, {skipped} skipped")


def _git_merge_text(ours: str, base: str, theirs: str) -> tuple[str, bool] | None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_root = Path(tmp_dir)
        ours_path = tmp_root / "ours.txt"
        base_path = tmp_root / "base.txt"
        theirs_path = tmp_root / "theirs.txt"
        ours_path.write_text(ours, encoding="utf-8")
        base_path.write_text(base, encoding="utf-8")
        theirs_path.write_text(theirs, encoding="utf-8")
        result = subprocess.run(
            ["git", "merge-file", "-p", str(ours_path), str(base_path), str(theirs_path)],
            capture_output=True,
            text=True,
            check=False,
        )
    if result.returncode not in {0, 1}:
        stderr = result.stderr.strip()
        if stderr:
            print(f"auto-merge: git merge-file failed: {stderr}")
        return None
    return result.stdout.rstrip(), result.returncode == 0


def auto_merge_conflicts(project: WorkflowProject, conflicts: list[ConflictEntry]) -> list[ConflictEntry]:
    if not conflicts:
        return conflicts
    if shutil.which("git") is None:
        print("auto-merge: skipped (git not found)")
        return conflicts

    previous_state = load_tracking_state(project)
    merged_entries: list[ConflictEntry] = []
    merged_count = 0
    skipped_count = 0

    for entry in conflicts:
        if entry.status != "stale" or not entry.merged_path.exists():
            merged_entries.append(entry)
            continue

        previous_record = previous_state.get(entry.key.tracking_id)
        previous_sources = previous_record.get("sources", {}) if isinstance(previous_record, dict) else {}
        if not isinstance(previous_sources, dict):
            merged_entries.append(entry)
            skipped_count += 1
            continue

        merged_text = entry.merged_path.read_text(encoding="utf-8")
        _, metadata, ours_body = split_file_sections(merged_text, project.object_start_re)
        if not metadata:
            merged_entries.append(entry)
            skipped_count += 1
            continue

        changed_sources: list[tuple[str, str, str]] = []
        for source in sorted(entry.sources, key=lambda source: source.ref):
            previous_source = previous_sources.get(source.ref)
            if not isinstance(previous_source, dict):
                continue
            previous_body = previous_source.get("body")
            previous_hash = previous_source.get("hash")
            if not isinstance(previous_body, str) or not isinstance(previous_hash, str):
                continue
            if previous_hash == source.source_hash:
                continue
            changed_sources.append((source.ref, previous_body, source.body))

        if not changed_sources:
            merged_entries.append(entry)
            skipped_count += 1
            continue

        current_body = ours_body.rstrip()
        clean_merge = True
        for ref, previous_body, current_source_body in changed_sources:
            merge_result = _git_merge_text(
                current_body,
                previous_body.rstrip(),
                current_source_body.rstrip(),
            )
            if merge_result is None:
                clean_merge = False
                break
            merged_body, merged_cleanly = merge_result
            if not merged_cleanly:
                print(f"auto-merge: unresolved merge for {entry.key.tracking_id} against {ref}")
                clean_merge = False
                break
            current_body = merged_body.rstrip()

        if not clean_merge:
            merged_entries.append(entry)
            skipped_count += 1
            continue

        refreshed_metadata: dict[str, object] = dict(metadata)
        refreshed_metadata.pop("name", None)
        refreshed_metadata.pop("upstream_status", None)
        refreshed_text = (
            render_metadata_block(refreshed_metadata, metadata_line_template=project.metadata_line_template)
            + current_body
            + "\n"
        )
        if refreshed_text != merged_text:
            entry.merged_path.write_text(refreshed_text, encoding="utf-8")
            print(f"auto-merged: {entry.merged_path.relative_to(project.root)}")

        merged_entries.append(replace(entry, status="auto-merged"))
        merged_count += 1

    print(f"auto-merge: {merged_count} merged, {skipped_count} skipped")
    return merged_entries
