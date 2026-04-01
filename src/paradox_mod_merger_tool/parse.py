from __future__ import annotations

from pathlib import Path
import re


FILE_VARIABLE_DEFINITION_RE = re.compile(r"^\s*(@\w+)\s*=\s*(\d+(?:\.\d*)?)\s*$", re.MULTILINE)
FILE_VARIABLE_TOKEN_RE = re.compile(r"@\w+")


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


def collect_file_variable_definitions(text: str) -> dict[str, str]:
    definitions: dict[str, str] = {}
    for match in FILE_VARIABLE_DEFINITION_RE.finditer(text):
        variable_name = match.group(1)
        definitions[variable_name] = f"{variable_name} = {match.group(2)}"
    return definitions


def collect_file_variable_usages(text: str) -> list[str]:
    seen: set[str] = set()
    usages: list[str] = []
    for match in FILE_VARIABLE_TOKEN_RE.finditer(text):
        variable_name = match.group(0)
        if variable_name in seen:
            continue
        seen.add(variable_name)
        usages.append(variable_name)
    return usages


def prepend_used_file_variables(body: str, definitions: dict[str, str]) -> str:
    if not definitions:
        return body

    existing_definitions = {
        match.group(1)
        for match in FILE_VARIABLE_DEFINITION_RE.finditer(body)
    }
    used_definitions: list[str] = []
    for variable_name in collect_file_variable_usages(body):
        if variable_name in existing_definitions:
            continue
        definition = definitions.get(variable_name)
        if definition:
            used_definitions.append(definition)

    if not used_definitions:
        return body
    return "\n".join(used_definitions) + "\n\n" + body


def split_leading_file_variable_definitions(text: str) -> tuple[dict[str, str], str]:
    definitions: dict[str, str] = {}
    lines = text.splitlines()
    index = 0

    # Header lines are the leading block that can contain blank lines, comments,
    # and file-variable definitions. Stop when the first body line appears.
    header_lines: list[str] = []
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped or stripped.startswith("#") or FILE_VARIABLE_DEFINITION_RE.match(stripped):
            header_lines.append(lines[index])
            index += 1
            continue
        break

    kept_lines: list[str] = []
    header_has_future_variable: list[bool] = [False] * len(header_lines)
    seen_future_variable = False
    for i in range(len(header_lines) - 1, -1, -1):
        header_has_future_variable[i] = seen_future_variable
        if FILE_VARIABLE_DEFINITION_RE.match(header_lines[i].strip()):
            seen_future_variable = True

    for i, line in enumerate(header_lines):
        stripped = line.strip()
        match = FILE_VARIABLE_DEFINITION_RE.match(stripped)
        if match:
            variable_name = match.group(1)
            definitions[variable_name] = f"{variable_name} = {match.group(2)}"
            continue
        if stripped.startswith("#") and header_has_future_variable[i]:
            continue
        kept_lines.append(line)

    remainder = "\n".join([*kept_lines, *lines[index:]]).strip()
    return definitions, remainder
