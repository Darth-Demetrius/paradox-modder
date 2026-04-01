from __future__ import annotations

import argparse
from pathlib import Path

from .commands import run_assemble, run_create, run_init, run_scan
from .project import load_project


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Paradox mod merge workspace tool.")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Project root containing _merged/_build and mod inputs.",
    )
    parser.add_argument(
        "--config-file",
        type=Path,
        default=None,
        help="Path to project TOML config. Defaults to mod_merger.toml or .mod-merger.toml discovered from project root.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("scan", help="Analyze configured sources, snapshot conflicts, and seed review records.")
    subparsers.add_parser("assemble", help="Assemble review records from _merged into the final _build output.")
    create_parser = subparsers.add_parser("create", help="Create _merged review records from a manifest for new or modified files.")
    create_parser.add_argument(
        "--manifest-file",
        type=Path,
        required=True,
        help="Path to a TOML manifest describing object, preamble, or whole-file records.",
    )
    init_parser = subparsers.add_parser(
        "init",
        help="Initialise a new mod-merger project: write mod_merger.toml and create working directories.",
    )
    init_parser.add_argument(
        "--my-mod-name",
        "--patch-name",
        required=True,
        help='Human-readable name of your my-mod input directory (e.g. "My Compatibility Mod").',
    )
    init_parser.add_argument(
        "--my-mod-dir",
        "--patch-dir",
        dest="my_mod_dir",
        default=None,
        help="Relative path for mods.my_mod input directory. Defaults to the patch name.",
    )
    init_parser.add_argument(
        "--mod",
        dest="mods",
        action="append",
        default=[],
        metavar="ALIAS=PATH",
        help=(
            "Add a mod alias mapping. Repeat for each mod. "
            'Example: --mod pd_arcologies="External Mods/Planetary Diversity - More Arcologies"'
        ),
    )
    init_parser.add_argument(
        "--source-mod",
        dest="source_mods",
        action="append",
        default=[],
        metavar="ALIAS",
        help="Mark an alias as a conflict-source mod (repeat as needed).",
    )
    init_parser.add_argument(
        "--filter-mod",
        dest="filter_mods",
        action="append",
        default=[],
        metavar="ALIAS",
        help="Mark an alias as a conflict-filter mod (repeat as needed).",
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing mod_merger.toml.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "init":
        extra_mods: list[tuple[str, str]] = []
        for spec in args.mods:
            if "=" not in spec:
                parser.error(f"--mod value must be ALIAS=PATH, got: {spec!r}")
            alias, _, path = spec.partition("=")
            extra_mods.append((alias.strip(), path.strip()))
        return run_init(
            project_root=args.project_root,
            patch_name=args.my_mod_name,
            my_mod_dir_rel=args.my_mod_dir,
            extra_mods=extra_mods,
            source_mod_aliases=args.source_mods,
            conflict_filter_mods=args.filter_mods,
            force=args.force,
        )

    project = load_project(project_root=args.project_root, config_file=args.config_file)
    if args.command == "scan":
        return run_scan(project)
    if args.command == "create":
        return run_create(project, manifest_file=args.manifest_file)
    return run_assemble(project)
