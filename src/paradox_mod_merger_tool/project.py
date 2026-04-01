from __future__ import annotations

import itertools
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONFIG_FILENAMES = ("mod_merger.toml", ".mod-merger.toml")
DEFAULT_METADATA_LINE_TEMPLATE = "# {key}: {value}"
DEFAULT_DESCRIPTOR_PATTERN = r'^(?P<key>[A-Za-z_]+)="(?P<value>[^"]*)"$'
DEFAULT_OBJECT_START_PATTERN = r"^([A-Za-z0-9_]+)\s*=\s*{\s*$"


@dataclass(frozen=True)
class WorkflowProject:
    root: Path
    config_path: Path
    build_dir: Path
    merged_dir: Path
    conflicts_dir: Path
    tracking_dir: Path
    file_replace_template: str
    file_merge_template: str
    snapshot_name_template: str
    metadata_line_template: str
    descriptor_re: re.Pattern[str]
    object_start_re: re.Pattern[str]
    mod_paths: dict[str, str]
    my_mod_alias: str
    my_mod_dir: Path
    allowed_conflict_pairs: set[frozenset[str]]
    mod_priority: dict[str, int]

    @property
    def alias_to_path(self) -> dict[str, str]:
        return dict(self.mod_paths)

    @property
    def path_to_alias(self) -> dict[str, str]:
        return {path: alias for alias, path in self.alias_to_path.items()}

    @property
    def mods_to_check(self) -> list[str]:
        return [
            mod_path
            for alias, mod_path in self.alias_to_path.items()
        ]

    @property
    def source_mods(self) -> dict[str, str]:
        return {
            mod_path: alias
            for alias, mod_path in self.alias_to_path.items()
            if alias != "vanilla"
        }


def _parse_pair(value: Any, key_name: str) -> frozenset[str]:
    if not isinstance(value, list) or len(value) != 2 or not all(isinstance(item, str) for item in value):
        raise ValueError(f"conflicts.{key_name} entries must be [alias_a, alias_b]")
    if value[0] == value[1]:
        raise ValueError(f"conflicts.{key_name} entries must reference two distinct aliases")
    return frozenset(value)


def _compile_allowed_pairs(conflicts: dict[str, Any], known_aliases: set[str]) -> set[frozenset[str]]:
    allowed_pairs: set[frozenset[str]] = set()

    include_pairs = conflicts.get("include_pairs", [])
    if include_pairs:
        if not isinstance(include_pairs, list):
            raise ValueError("conflicts.include_pairs must be a list")
        for pair in include_pairs:
            allowed_pairs.add(_parse_pair(pair, "include_pairs"))

    rules = conflicts.get("rules", [])
    if rules:
        if not isinstance(rules, list):
            raise ValueError("conflicts.rules must be a list of tables")
        for rule in rules:
            if not isinstance(rule, dict):
                raise ValueError("conflicts.rules entries must be tables")
            any_from = rule.get("any_from", [])
            with_any = rule.get("with_any", [])
            if not isinstance(any_from, list) or not all(isinstance(item, str) for item in any_from):
                raise ValueError("conflicts.rules.any_from must be a string list")
            if not isinstance(with_any, list) or not all(isinstance(item, str) for item in with_any):
                raise ValueError("conflicts.rules.with_any must be a string list")
            for left, right in itertools.product(any_from, with_any):
                if left != right:
                    allowed_pairs.add(frozenset((left, right)))

    exclude_pairs = conflicts.get("exclude_pairs", [])
    if exclude_pairs:
        if not isinstance(exclude_pairs, list):
            raise ValueError("conflicts.exclude_pairs must be a list")
        for pair in exclude_pairs:
            allowed_pairs.discard(_parse_pair(pair, "exclude_pairs"))

    unknown_aliases = {alias for pair in allowed_pairs for alias in pair if alias not in known_aliases}
    if unknown_aliases:
        unknown = ", ".join(sorted(unknown_aliases))
        raise ValueError(f"Unknown aliases referenced in conflicts config: {unknown}")

    return allowed_pairs


def _resolve_project_root(project_root: Path | None, config_file: Path | None) -> tuple[Path, Path]:
    if config_file is not None:
        config_path = config_file.resolve()
        root = (project_root or Path.cwd()).resolve()
        return root, config_path

    search_root = (project_root or Path.cwd()).resolve()
    for candidate_root in (search_root, *search_root.parents):
        for name in CONFIG_FILENAMES:
            candidate = candidate_root / name
            if candidate.exists():
                return candidate_root, candidate
    raise FileNotFoundError(
        "Could not find project config. Pass --config-file or add mod_merger.toml/.mod-merger.toml to the project root."
    )


def _require_table(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"Missing or invalid [{key}] table in config")
    return value


def load_project(project_root: str | Path | None = None, config_file: str | Path | None = None) -> WorkflowProject:
    root_hint = Path(project_root).resolve() if project_root is not None else None
    config_hint = Path(config_file).resolve() if config_file is not None else None
    root, config_path = _resolve_project_root(root_hint, config_hint)

    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)

    paths = _require_table(raw, "paths")
    templates = _require_table(raw, "templates")
    mods_table = _require_table(raw, "mods")

    mod_paths: dict[str, str] = {}
    for alias, rel_path in mods_table.items():
        if not isinstance(alias, str) or not isinstance(rel_path, str):
            raise ValueError("mods entries must be string = string")
        mod_paths[alias] = rel_path

    mod_priority_raw = _require_table(raw, "priority") if "priority" in raw else {}

    conflicts = raw.get("conflicts", {})
    if not isinstance(conflicts, dict):
        raise ValueError("conflicts must be a table")

    mod_priority = {alias: int(value) for alias, value in mod_priority_raw.items()}

    vanilla_alias = next((alias for alias in mod_paths if alias.strip().lower() == "vanilla"), None)
    if vanilla_alias is None:
        aliases = ", ".join(sorted(mod_paths))
        raise ValueError(
            "mods.vanilla is required and should point to the base game directory "
            f"(or \"\" for project-root vanilla files). Found aliases: [{aliases}]"
        )

    my_mod_alias = next((alias for alias in mod_paths if alias.strip().lower() == "my_mod"), None)
    if my_mod_alias is None:
        aliases = ", ".join(sorted(mod_paths))
        raise ValueError(
            "mods.my_mod is required and must point to your input mod directory. "
            'Example: [mods]\nmy_mod = "_My Mod"\n'
            "Note: [paths].build is the output directory. "
            f"Found aliases: [{aliases}]"
        )
    if not mod_paths[my_mod_alias].strip():
        raise ValueError(
            "mods.my_mod must be a non-empty path to your input mod directory. "
            "Note: [paths].build is the output directory."
        )

    known_aliases = set(mod_paths)
    allowed_conflict_pairs = _compile_allowed_pairs(conflicts, known_aliases)

    descriptor_pattern = str(raw.get("regex", {}).get("descriptor", DEFAULT_DESCRIPTOR_PATTERN)) if isinstance(raw.get("regex"), dict) else DEFAULT_DESCRIPTOR_PATTERN
    object_start_pattern = str(raw.get("regex", {}).get("object_start", DEFAULT_OBJECT_START_PATTERN)) if isinstance(raw.get("regex"), dict) else DEFAULT_OBJECT_START_PATTERN

    return WorkflowProject(
        root=root,
        config_path=config_path,
        build_dir=root / str(paths["build"]),
        merged_dir=root / str(paths["merged"]),
        conflicts_dir=root / str(paths["conflicts"]),
        tracking_dir=root / str(paths["tracking"]),
        file_replace_template=str(templates["replace"]),
        file_merge_template=str(templates["merge"]),
        snapshot_name_template=str(templates["snapshot"]),
        metadata_line_template=str(templates.get("metadata_line", DEFAULT_METADATA_LINE_TEMPLATE)),
        descriptor_re=re.compile(descriptor_pattern),
        object_start_re=re.compile(object_start_pattern, re.MULTILINE),
        mod_paths=mod_paths,
        my_mod_alias=my_mod_alias,
        my_mod_dir=root / mod_paths[my_mod_alias],
        allowed_conflict_pairs=allowed_conflict_pairs,
        mod_priority=mod_priority,
    )
