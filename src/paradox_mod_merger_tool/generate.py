from __future__ import annotations

import tomllib
from pathlib import Path
from typing import cast
from typing import Any

from .domain import ConflictKey, PREAMBLE_NAME, WHOLE_FILE_NAME
from .layout import merged_path
from .metadata import render_metadata_block
from .parse import iter_object_blocks
from .project import WorkflowProject


def coerce_sort_key(raw_sort_key: Any, default_name: str, default_priority: int) -> tuple[int, int, str]:
    if isinstance(raw_sort_key, (list, tuple)) and len(raw_sort_key) == 3:
        return (int(raw_sort_key[0]), int(raw_sort_key[1]), str(raw_sort_key[2]))
    return (default_priority, 0, default_name)


def parse_generated_name(project: WorkflowProject, body: str) -> str:
    blocks = iter_object_blocks(body if body.endswith("\n") else body + "\n", project.object_start_re)
    if len(blocks) != 1:
        raise ValueError("Generated object records must provide name/id or contain exactly one object block")
    return blocks[0][0]


def manifest_records(manifest_file: Path) -> list[dict[str, Any]]:
    with manifest_file.open("rb") as handle:
        raw = tomllib.load(handle)
    records = raw.get("records")
    if not isinstance(records, list) or not all(isinstance(record, dict) for record in records):
        raise ValueError("Manifest must contain [[records]] tables")
    return records


def run_generate(project: WorkflowProject, manifest_file: Path) -> int:
    created = 0
    for index, record in enumerate(manifest_records(manifest_file), start=1):
        record_type = cast(str, str(record.get("type", "object")))
        if record_type not in {"object", "preamble", "file"}:
            raise ValueError(f"Unsupported record type at manifest record {index}: {record_type}")
        source_path = str(record.get("source_file", record.get("output", ""))).strip()
        output_rel = str(record.get("output", source_path)).strip()
        body = str(record.get("body", "")).rstrip()
        if not output_rel or not body:
            raise ValueError(f"Manifest record {index} must define output/source_file and body")
        raw_name = str(record.get("name", record.get("id", ""))).strip()
        if record_type == "object":
            name = raw_name or parse_generated_name(project, body)
        elif record_type == "preamble":
            name = raw_name or PREAMBLE_NAME
        else:
            name = raw_name or WHOLE_FILE_NAME
        key = ConflictKey(source_path or output_rel, name, cast(Any, record_type))
        output_path = merged_path(project, output_rel, key)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            render_metadata_block(
                {
                    "output": output_rel,
                    "record_type": record_type,
                    "name": name,
                    "source_path": source_path or output_rel,
                    "upstream_status": "generated",
                    "sort_key": coerce_sort_key(record.get("sort_key"), name, len(project.mod_priority)),
                    "sources": record.get("sources", []),
                },
                metadata_line_template=project.metadata_line_template,
            )
            + body
            + "\n",
            encoding="utf-8",
        )
        print(f"created: {output_path.relative_to(project.root)}")
        created += 1
    print(f"create: {created} records from {manifest_file}")
    return 0
