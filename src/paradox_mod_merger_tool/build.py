from __future__ import annotations

import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any

from .layout import active_build_dir, copy_patch_metadata, derive_output_from_refs
from .metadata import read_merged_record, split_file_sections
from .project import WorkflowProject
from .scan import iter_mod_text_files


def collect_preambles(project: WorkflowProject) -> dict[str, str]:
    preambles: dict[str, str] = {}
    for mod_name in project.mods_to_check:
        mod_dir = project.root / mod_name
        for path in iter_mod_text_files(project, mod_name):
            ref = f"{mod_name}/{path.relative_to(mod_dir).as_posix()}"
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

    for merged_file in sorted(project.merged_dir.rglob("*.txt")):
        merged_parts = merged_file.relative_to(project.merged_dir).parts
        if any(part.startswith(".") for part in merged_parts):
            continue
        merged_files += 1
        merged_record = read_merged_record(merged_file, project.object_start_re, len(project.mod_priority))
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
            preamble = bucket["preamble"][1].rstrip() if bucket["preamble"] is not None else output_preambles.get(rel_text, "").rstrip()
            if preamble:
                sections.append(preamble)
                built_records += 1
            object_bodies = [body.rstrip() for _, body in sorted(bucket["objects"])]
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
