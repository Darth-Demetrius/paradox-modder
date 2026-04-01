from __future__ import annotations

import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any

from .layout import active_build_dir, copy_patch_metadata, derive_output_from_refs
from .metadata import read_merged_record, split_file_sections
from .parse import collect_file_variable_usages, split_leading_file_variable_definitions
from .project import WorkflowProject
from .scan import iter_mod_text_files


def collect_preambles(project: WorkflowProject) -> dict[str, str]:
    preambles: dict[str, str] = {}
    for mod_name in project.mods_to_check:
        mod_dir = project.root / mod_name
        alias = project.path_to_alias.get(mod_name, mod_name.lower())
        for path in iter_mod_text_files(project, mod_name):
            ref = f"{alias}/{path.relative_to(mod_dir).as_posix()}"
            output_rel = derive_output_from_refs(project, [ref])
            if output_rel in preambles:
                continue
            preamble, _, object_body = split_file_sections(path.read_text(encoding="utf-8"), project.object_start_re)
            if preamble and object_body:
                preambles[output_rel] = preamble.rstrip()
    return preambles


def run_build(project: WorkflowProject) -> int:
    build_dir = active_build_dir(project)
    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)
    copy_patch_metadata(project, build_dir)
    output_preambles = collect_preambles(project)
    output_records: dict[str, dict[str, Any]] = defaultdict(lambda: {"objects": [], "preamble": None, "file": None})
    merged_files = 0
    skipped_excluded = 0

    for merged_file in sorted(project.merged_dir.rglob("*.txt")):
        merged_parts = merged_file.relative_to(project.merged_dir).parts
        if any(part.startswith(".") for part in merged_parts):
            continue
        merged_files += 1
        try:
            merged_record = read_merged_record(merged_file, project.object_start_re, len(project.mod_priority))
        except ValueError as exc:
            if "Missing # path:" in str(exc):
                skipped_excluded += 1
                continue
            raise
        if not merged_record.output_rel:
            skipped_excluded += 1
            continue
        bucket = output_records[merged_record.output_rel]
        if merged_record.record_type == "file":
            bucket["file"] = (merged_record.sort_key, merged_record.body)
        elif merged_record.record_type == "preamble":
            current = bucket["preamble"]
            if current is None or merged_record.sort_key < current[0]:
                bucket["preamble"] = (merged_record.sort_key, merged_record.body)
        elif merged_record.body:
            bucket["objects"].append((merged_record.sort_key, merged_record.body))

    if merged_files == 0:
        print("assemble: 0 records → 0 files")
        print("hint: _merged is empty. Run scan/create, resolve the review records, then assemble.")
        return 0
    if skipped_excluded:
        print(f"assemble: skipped {skipped_excluded} records with empty or missing # path")

    built_outputs = 0
    built_records = 0
    for rel_text, bucket in sorted(output_records.items()):
        out = build_dir / rel_text
        out.parent.mkdir(parents=True, exist_ok=True)

        if bucket["file"] is not None:
            rendered = bucket["file"][1].rstrip() + "\n"
            built_records += 1
        else:
            sections: list[str] = []
            file_variable_definitions: dict[str, str] = {}
            raw_preamble = bucket["preamble"][1].rstrip() if bucket["preamble"] is not None else output_preambles.get(rel_text, "").rstrip()
            preamble_definitions, preamble = split_leading_file_variable_definitions(raw_preamble)
            for variable_name, definition in preamble_definitions.items():
                file_variable_definitions.setdefault(variable_name, definition)
            object_bodies: list[str] = []
            used_file_variables: set[str] = set()
            for _, object_body in sorted(bucket["objects"]):
                leading_definitions, stripped_object_body = split_leading_file_variable_definitions(object_body)
                for variable_name, definition in leading_definitions.items():
                    file_variable_definitions.setdefault(variable_name, definition)
                for variable_name in collect_file_variable_usages(stripped_object_body):
                    used_file_variables.add(variable_name)
                if stripped_object_body:
                    object_bodies.append(stripped_object_body.rstrip())

            variable_lines = [
                file_variable_definitions[variable_name]
                for variable_name in sorted(used_file_variables)
                if variable_name in file_variable_definitions
            ]
            if variable_lines:
                sections.append("\n".join(variable_lines))
            if preamble:
                sections.append(preamble)
                built_records += 1
            if object_bodies:
                sections.extend(object_bodies)
                built_records += len(object_bodies)
            if not sections:
                continue
            rendered = "\n\n".join(sections).rstrip() + "\n"

        out.write_text(rendered, encoding="utf-8")
        built_outputs += 1
        print(f"built: {(project.build_dir / rel_text).relative_to(project.root)}")

    print(f"assemble: {built_records} records → {built_outputs} files")
    return 0
