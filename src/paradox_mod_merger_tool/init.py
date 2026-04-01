from __future__ import annotations

from pathlib import Path


_DEFAULT_PATHS = {
    "build": "_build",
    "merged": "_merged",
    "conflicts": "_conflicts",
    "tracking": "_tracking",
}

_DEFAULT_TEMPLATES = {
    "replace": "{source_dir}/{source_name}_replace_{source_mod_id}.txt",
    "merge": "{source_dir}/_all_merged_common_items_replace.txt",
    "snapshot": "{mod_name}_{source_name}.txt",
    "metadata_line": "# {key}: {value}",
}

_DESCRIPTOR_TEMPLATE = """\
name="{name}"
version="0.1"
supported_version="*"
"""


def _slugify(name: str) -> str:
    """Convert a human-readable name to a safe directory name."""
    return name.replace("/", "-").replace("\\", "-").strip()


def _build_config(
    my_mod_dir_rel: str,
    mod_aliases: dict[str, str],
    source_mod_aliases: list[str],
    conflict_filter_mods: list[str],
    mod_priority: dict[str, int],
) -> str:
    lines: list[str] = []

    lines.append("[paths]")
    for key, val in _DEFAULT_PATHS.items():
        lines.append(f'{key} = "{val}"')
    lines.append("")

    lines.append("[templates]")
    for key, val in _DEFAULT_TEMPLATES.items():
        lines.append(f'{key} = "{val}"')
    lines.append("")

    lines.append("[mods]")
    for alias, path in mod_aliases.items():
        lines.append(f'{alias} = "{path}"')
    lines.append(f'my_mod = "{my_mod_dir_rel}"')
    lines.append("")

    lines.append("[conflicts]")
    if source_mod_aliases and conflict_filter_mods:
        source_list = ", ".join(f'"{a}"' for a in source_mod_aliases)
        filter_list = ", ".join(f'"{a}"' for a in conflict_filter_mods)
        lines.append("[[conflicts.rules]]")
        lines.append(f"any_from = [{source_list}]")
        lines.append(f"with_any = [{filter_list}]")
    lines.append("")

    lines.append("[priority]")
    for alias, priority in mod_priority.items():
        lines.append(f"{alias} = {priority}")
    lines.append("")

    return "\n".join(lines)


def run_init(
    project_root: Path,
    patch_name: str,
    my_mod_dir_rel: str | None,
    extra_mods: list[tuple[str, str]],
    source_mod_aliases: list[str],
    conflict_filter_mods: list[str],
    force: bool = False,
) -> int:
    """Initialise a new mod-merger project at *project_root*.

    Creates:
    - ``mod_merger.toml`` – project config
    - ``<my_mod_dir>/`` – my-mod directory with a skeleton ``descriptor.mod``
    - ``_merged/``, ``_build/``, ``_conflicts/`` – working directories

    Parameters
    ----------
    project_root:
        Directory that will become the project root.
    patch_name:
        Human-readable name for the my-mod input directory (used in ``descriptor.mod``).
    my_mod_dir_rel:
        Relative path for the mods.my_mod input directory. Defaults to the patch name.
    extra_mods:
        Additional ``(alias, relative_path)`` pairs added to ``mods``.
    source_mod_aliases:
        Aliases that should be scanned as conflict sources.
    conflict_filter_mods:
        Aliases used to filter which conflicts are surfaced.
    force:
        Overwrite ``mod_merger.toml`` if it already exists.
    """
    project_root = project_root.resolve()
    project_root.mkdir(parents=True, exist_ok=True)

    config_path = project_root / "mod_merger.toml"
    if config_path.exists() and not force:
        print(
            f"error: {config_path} already exists. "
            "Pass --force to overwrite or edit the file manually."
        )
        return 1

    if my_mod_dir_rel is None:
        my_mod_dir_rel = _slugify(patch_name)

    # Build the alias map.  vanilla (empty path = game root) is always present.
    mod_aliases: dict[str, str] = {"vanilla": ""}
    for alias, path in extra_mods:
        mod_aliases[alias] = path

    # vanilla is always priority 0; assign ascending priority to the rest.
    mod_priority: dict[str, int] = {"vanilla": 0}
    for idx, alias in enumerate(
        (alias for alias in mod_aliases if alias != "vanilla"), 1
    ):
        mod_priority[alias] = idx

    config_text = _build_config(
        my_mod_dir_rel=my_mod_dir_rel,
        mod_aliases=mod_aliases,
        source_mod_aliases=source_mod_aliases,
        conflict_filter_mods=conflict_filter_mods,
        mod_priority=mod_priority,
    )
    config_path.write_text(config_text, encoding="utf-8")
    print(f"wrote: {config_path.relative_to(project_root)}")

    # Create working directories.
    for rel in (_DEFAULT_PATHS["merged"], _DEFAULT_PATHS["build"], _DEFAULT_PATHS["conflicts"]):
        (project_root / rel).mkdir(parents=True, exist_ok=True)

    # Create my_mod directory with a skeleton descriptor.
    my_mod_dir = project_root / my_mod_dir_rel
    my_mod_dir.mkdir(parents=True, exist_ok=True)
    descriptor_path = my_mod_dir / "descriptor.mod"
    if not descriptor_path.exists():
        descriptor_path.write_text(
            _DESCRIPTOR_TEMPLATE.format(name=patch_name), encoding="utf-8"
        )
        print(f"wrote: {descriptor_path.relative_to(project_root)}")
    else:
        print(f"skipped (exists): {descriptor_path.relative_to(project_root)}")

    print("init: project structure created successfully.")
    print(f"  config:    {config_path.relative_to(project_root)}")
    print(f"  my mod:    {my_mod_dir.relative_to(project_root)}/")
    print("Next steps:")
    print("  1. Edit mod_merger.toml to add your source mod paths (including mods.my_mod).")
    print("  2. Run: paradox-mod-merger --project-root . scan")
    print("  3. Resolve files in _merged/ (optional: bash _conflicts/review_conflicts.sh)")
    print("  4. Run: paradox-mod-merger --project-root . assemble")
    print("  5. Optional for manifest workflows:")
    print("     paradox-mod-merger --project-root . create --manifest-file create.toml")
    return 0
