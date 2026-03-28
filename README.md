# Paradox Mod Merger Tool

Reusable Python CLI for Paradox mod merge-prep and build workflows.

The tool is intentionally config-driven so individual patch repos can keep thin wrappers and a project-specific config file while reusing the same parsing and assembly logic.

## What it does

- scans configured source mods for object-level conflicts
- snapshots conflicting upstream object blocks
- seeds per-object merge files into `_Merged/`
- writes generated conflict review artifacts into `_Conflicts/`
- assembles resolved `_Merged/` records into `_build/`
- keeps project-specific paths, mod aliases, and filename templates in TOML config

## Install

```bash
cd '/disks/Storage/Code Workspaces/Paradox Mod Merger Tool'
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Usage

With an installed console script:

```bash
paradox-mod-merger --project-root /path/to/project --config-file /path/to/project/.scripts/project-config.toml prep
paradox-mod-merger --project-root /path/to/project --config-file /path/to/project/.scripts/project-config.toml build
```

Without installation:

```bash
cd '/disks/Storage/Code Workspaces/Paradox Mod Merger Tool'
PYTHONPATH=src python3 -m paradox_mod_merger_tool --project-root /path/to/project --config-file /path/to/project/.scripts/project-config.toml prep
PYTHONPATH=src python3 -m paradox_mod_merger_tool --project-root /path/to/project --config-file /path/to/project/.scripts/project-config.toml build
```

## Project config

Projects can provide either:

- an explicit config path via `--config-file`
- a root-level `mod_merger.toml`
- a root-level `.mod-merger.toml`

See [examples/bpvr_patch.toml](/disks/Storage/Code%20Workspaces/Paradox%20Mod%20Merger%20Tool/examples/bpvr_patch.toml) for a concrete configuration.

## Development

Run the tests with:

```bash
cd '/disks/Storage/Code Workspaces/Paradox Mod Merger Tool'
PYTHONPATH=src python3 -m unittest discover -s tests -v
```
