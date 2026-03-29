from __future__ import annotations

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
    patch_dir: Path
    file_replace_template: str
    file_merge_template: str
    snapshot_name_template: str
    metadata_line_template: str
    descriptor_re: re.Pattern[str]
    object_start_re: re.Pattern[str]
    mod_aliases: dict[str, str]
    source_mod_aliases: set[str]
    conflict_filter_source_mods: set[str]
    mod_priority: dict[str, int]

    @property
    def alias_to_path(self) -> dict[str, str]:
        return dict(self.mod_aliases)

    @property
    def path_to_alias(self) -> dict[str, str]:
        return {path: alias for alias, path in self.alias_to_path.items()}

    @property
    def mods_to_check(self) -> list[str]:
        return list(self.alias_to_path.values())

    @property
    def source_mods(self) -> dict[str, str]:
        return {self.alias_to_path[alias]: alias for alias in self.source_mod_aliases if alias in self.alias_to_path}

    @property
    def patch_mod(self) -> str:
        try:
            return self.alias_to_path["my_patch"]
        except KeyError as exc:
            raise ValueError("Project config must define mods.aliases.my_patch") from exc


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
    mods = _require_table(raw, "mods")
    mod_aliases_raw = _require_table(mods, "aliases")
    mod_priority_raw = _require_table(mods, "priority")

    mod_aliases: dict[str, str] = {}
    for alias, rel_path in mod_aliases_raw.items():
        if not isinstance(alias, str) or not isinstance(rel_path, str):
            raise ValueError("mods.aliases entries must be string = string")
        mod_aliases[alias] = rel_path

    source_mod_aliases = set(mods.get("source_mod_aliases", []))
    conflict_filter_source_mods = set(mods.get("conflict_filter_source_mods", []))
    if not all(isinstance(item, str) for item in source_mod_aliases | conflict_filter_source_mods):
        raise ValueError("mods.source_mod_aliases and mods.conflict_filter_source_mods must be string lists")

    mod_priority = {alias: int(value) for alias, value in mod_priority_raw.items()}

    descriptor_pattern = str(raw.get("regex", {}).get("descriptor", DEFAULT_DESCRIPTOR_PATTERN)) if isinstance(raw.get("regex"), dict) else DEFAULT_DESCRIPTOR_PATTERN
    object_start_pattern = str(raw.get("regex", {}).get("object_start", DEFAULT_OBJECT_START_PATTERN)) if isinstance(raw.get("regex"), dict) else DEFAULT_OBJECT_START_PATTERN

    return WorkflowProject(
        root=root,
        config_path=config_path,
        build_dir=root / str(paths["build"]),
        merged_dir=root / str(paths["merged"]),
        conflicts_dir=root / str(paths["conflicts"]),
        tracking_dir=root / str(paths["tracking"]),
        patch_dir=root / str(paths["patch"]),
        file_replace_template=str(templates["replace"]),
        file_merge_template=str(templates["merge"]),
        snapshot_name_template=str(templates["snapshot"]),
        metadata_line_template=str(templates.get("metadata_line", DEFAULT_METADATA_LINE_TEMPLATE)),
        descriptor_re=re.compile(descriptor_pattern),
        object_start_re=re.compile(object_start_pattern, re.MULTILINE),
        mod_aliases=mod_aliases,
        source_mod_aliases=source_mod_aliases,
        conflict_filter_source_mods=conflict_filter_source_mods,
        mod_priority=mod_priority,
    )
