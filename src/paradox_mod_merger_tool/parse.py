from __future__ import annotations

from pathlib import Path
import re


def _parse_descriptor_fields(mod_dir: Path, descriptor_re: re.Pattern[str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    descriptor_path = mod_dir / "descriptor.mod"
    if not descriptor_path.exists():
        return fields
    for line in descriptor_path.read_text(encoding="utf-8").splitlines():
        match = descriptor_re.match(line.strip())
        if match:
            fields[match.group("key")] = match.group("value")
    return fields


def parse_descriptor(mod_dir: Path, descriptor_re: re.Pattern[str]) -> tuple[str, str, str]:
    fields = _parse_descriptor_fields(mod_dir, descriptor_re)
    game_version = fields["supported_version"].strip().removeprefix("v").removeprefix("V")
    mod_version = fields.get("version", "").strip().removeprefix("v").removeprefix("V")
    return game_version, mod_version, fields["remote_file_id"].strip()


def parse_mod_name(mod_dir: Path, descriptor_re: re.Pattern[str]) -> str:
    fields = _parse_descriptor_fields(mod_dir, descriptor_re)
    return fields["name"].strip()


def _with_immediate_leading_comments(text: str, object_start: int) -> int:
    current_line_start = text.rfind("\n", 0, object_start) + 1
    start = current_line_start
    probe_line_start = current_line_start
    while probe_line_start > 0:
        prev_line_end = probe_line_start - 1
        prev_line_start = text.rfind("\n", 0, prev_line_end) + 1
        prev_line = text[prev_line_start:prev_line_end]
        stripped = prev_line.strip()
        if stripped.startswith("#"):
            start = prev_line_start
            probe_line_start = prev_line_start
            continue
        break
    return start


def iter_object_blocks(text: str, object_start_re: re.Pattern[str]) -> list[tuple[str, str, int]]:
    results: list[tuple[str, str, int]] = []
    for position, match in enumerate(object_start_re.finditer(text), start=1):
        object_id, index, depth, in_string = match.group(1), match.start(), 0, False
        block_start = _with_immediate_leading_comments(text, match.start())
        while index < len(text):
            char = text[index]
            if char == '"' and (index == 0 or text[index - 1] != "\\"):
                in_string = not in_string
            elif not in_string:
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        results.append((object_id, text[block_start:index + 1], position))
                        break
            index += 1
        else:
            raise ValueError(f"Unbalanced braces while parsing object '{object_id}'")
    return results


def iter_object_ids(text: str, object_start_re: re.Pattern[str]) -> list[str]:
    return [object_id for object_id, _, _ in iter_object_blocks(text, object_start_re)]
