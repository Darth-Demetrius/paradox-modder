from __future__ import annotations

import argparse
from pathlib import Path

from .commands import run_assemble, run_create, run_scan
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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    project = load_project(project_root=args.project_root, config_file=args.config_file)
    if args.command == "scan":
        return run_scan(project)
    if args.command == "create":
        return run_create(project, manifest_file=args.manifest_file)
    return run_assemble(project)
