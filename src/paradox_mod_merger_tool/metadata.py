from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

LEADING_METADATA_KEYS = {
    "record_type",
    "path",
    "supported_version",
    "upstream_status",
    "sort_key",
    "sources",
}


@dataclass(frozen=True)
class MergedRecord:
    output_rel: str
    sort_key: tuple[int, int, str]
    record_type: str
    body: str


def read_leading_metadata_block(text: str) -> tuple[dict[str, Any], str]:
    metadata: dict[str, Any] = {}
    lines = text.splitlines()
    body_start = 0
    saw_metadata = False
    index = 0

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            if saw_metadata:
                body_start = index + 1
            index += 1
            continue
        if not stripped.startswith("#"):
            break
        key, sep, value = stripped[2:].partition(":")
        key = key.strip()
        value = value.lstrip()
        if not sep or key not in LEADING_METADATA_KEYS:
            break

        if key == "sources" and not value:
            sources: list[dict[str, str]] = []
            current: dict[str, str] = {}
            index += 1
            while index < len(lines):
                cont = lines[index].strip()
                if cont.startswith("#   "):
                    ck, csep, cv = cont[4:].partition(":")
                    if csep:
                        ck = ck.strip()
                        cv = cv.lstrip()
                        if ck == "path":
                            if current:
                                sources.append(current)
                            current = {"path": cv}
                        else:
                            current[ck] = cv
                    index += 1
                elif cont == "#" or not cont:
                    index += 1
                else:
                    break
            if current:
                sources.append(current)
            metadata["sources"] = sources
            saw_metadata = True
            body_start = index
            continue

        metadata[key] = value
        saw_metadata = True
        body_start = index + 1
        index += 1

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
) -> str:
    lines: list[str] = []
    for key, value in metadata.items():
        if key == "sources" and isinstance(value, list):
            source_lines = ["# sources:"]
            for i, source in enumerate(value):
                if i > 0:
                    source_lines.append("#")
                source_path = source.get("path", "")
                source_lines.append(f"#   path: {source_path}".rstrip())
                source_lines.append(f"#   supported_version: {source.get('supported_version', '')}".rstrip())
            lines.append("\n".join(source_lines))
        else:
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
    if "path" not in metadata:
        raise ValueError(f"Missing # path: in {merged_file}")
    output_rel = str(metadata.get("path", ""))
    return MergedRecord(
        output_rel=output_rel,
        sort_key=decode_sort_key(metadata.get("sort_key"), merged_file.stem, mod_priority_size),
        record_type=metadata.get("record_type", "object"),
        body=body,
    )
