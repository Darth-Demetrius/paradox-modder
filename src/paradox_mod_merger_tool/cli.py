from __future__ import annotations

import argparse
from pathlib import Path

from .project import load_project
from .workflow import run_build, run_prep


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Paradox mod merger workflow.")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Project root containing _Merged/_build and mod inputs.",
    )
    parser.add_argument(
        "--config-file",
        type=Path,
        default=None,
        help="Path to project TOML config. Defaults to mod_merger.toml or .mod-merger.toml discovered from project root.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("prep", help="Scan, snapshot, seed, and generate the merge helper script.")
    subparsers.add_parser("build", help="Assemble _Merged object files into _build output.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    project = load_project(project_root=args.project_root, config_file=args.config_file)
    if args.command == "prep":
        return run_prep(project)
    return run_build(project)
