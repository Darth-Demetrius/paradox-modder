from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
import re

LEADING_METADATA_KEYS = {
    "name",
    "output",
    "position",
    "record_type",
    "sort_key",
    "source_path",
    "sources",
    "supported_version",
    "upstream_status",
    "version",
}


@dataclass(frozen=True)
class MergedRecord:
    output_rel: str
    sort_key: tuple[int, int, str]
    record_type: str
    body: str


def read_leading_metadata_block(text: str) -> tuple[dict[str, str], str]:
    metadata: dict[str, str] = {}
    lines = text.splitlines()
    body_start = 0
    saw_metadata = False

    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            if saw_metadata:
                body_start = index + 1
            continue
        if stripped == "# auto-generated":
            saw_metadata = True
            metadata["auto-generated"] = "true"
            body_start = index + 1
            continue
        if not stripped.startswith("#"):
            break
        key, sep, value = stripped[2:].partition(": ")
        if not sep or key not in LEADING_METADATA_KEYS:
            break
        metadata[key] = value
        saw_metadata = True
        body_start = index + 1

    return metadata, "\n".join(lines[body_start:]).rstrip()


def split_file_sections(text: str, object_start_re: re.Pattern[str]) -> tuple[str, dict[str, str], str]:
    metadata, body = read_leading_metadata_block(text)
    if metadata:
        return "", metadata, body

    first_object = object_start_re.search(text)
    if not first_object:
        stripped = text.strip()
        return stripped, {}, ""

    object_body = text[first_object.start():].strip()
    preamble = text[: first_object.start()].strip()
    return preamble, {}, object_body


def render_metadata_block(
    metadata: dict[str, object],
    metadata_line_template: str,
    include_auto_generated: bool = False,
) -> str:
    lines: list[str] = []
    if include_auto_generated:
        lines.append("# auto-generated")
    for key, value in metadata.items():
        rendered = json.dumps(value, ensure_ascii=False) if isinstance(value, (list, tuple, dict)) else str(value)
        lines.append(metadata_line_template.format(key=key, value=rendered))
    return "\n".join(lines) + "\n\n"


def decode_sort_key(raw_sort_key: str | None, fallback_object_id: str, mod_priority_size: int) -> tuple[int, int, str]:
    if not raw_sort_key:
        return (mod_priority_size, 999, fallback_object_id)
    decoded = json.loads(raw_sort_key)
    return (int(decoded[0]), int(decoded[1]), str(decoded[2]))


def read_merged_record(merged_file: Path, object_start_re: re.Pattern[str], mod_priority_size: int) -> MergedRecord:
    _, metadata, body = split_file_sections(merged_file.read_text(encoding="utf-8"), object_start_re)
    output_rel = metadata.get("output")
    if not output_rel:
        raise ValueError(f"Missing # output: in {merged_file}")
    return MergedRecord(
        output_rel=output_rel,
        sort_key=decode_sort_key(metadata.get("sort_key"), merged_file.stem, mod_priority_size),
        record_type=metadata.get("record_type", "object"),
        body=body,
    )
