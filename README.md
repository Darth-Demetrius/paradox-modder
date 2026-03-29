# Paradox Mod Merger Tool

Reusable Python CLI for Paradox mod scan, review, and assembly workflows.

The tool is intentionally config-driven so individual patch repos can keep thin wrappers and a project-specific config file while reusing the same parsing and assembly logic.

## What it does

- scans configured source mods for object-level conflicts
- snapshots conflicting upstream object blocks
- tracks upstream hashes so repeated scans can flag stale or missing sources
- seeds per-object merge files into `_merged/`
- seeds preamble and whole-file records when those are the parts that differ
- writes conflict review artifacts into `_conflicts/`
- assembles resolved `_merged/` records into `_build/`
- creates review records from a manifest for simple mod creation workflows
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
paradox-mod-merger --project-root /path/to/project --config-file /path/to/project/.scripts/project-config.toml scan
paradox-mod-merger --project-root /path/to/project --config-file /path/to/project/.scripts/project-config.toml assemble
paradox-mod-merger --project-root /path/to/project --config-file /path/to/project/.scripts/project-config.toml create --manifest-file /path/to/project/.scripts/create.toml
```

Without installation:

```bash
cd '/disks/Storage/Code Workspaces/Paradox Mod Merger Tool'
PYTHONPATH=src python3 -m paradox_mod_merger_tool --project-root /path/to/project --config-file /path/to/project/.scripts/project-config.toml scan
PYTHONPATH=src python3 -m paradox_mod_merger_tool --project-root /path/to/project --config-file /path/to/project/.scripts/project-config.toml assemble
PYTHONPATH=src python3 -m paradox_mod_merger_tool --project-root /path/to/project --config-file /path/to/project/.scripts/project-config.toml create --manifest-file /path/to/project/.scripts/create.toml
```

## Scan Output

`scan` keeps `_merged/.upstream_tracking/state.json` between runs and records a status for each conflict entry:

- `new-upstream`: no local merged record exists yet, or a new upstream source appeared
- `stale`: an existing merged record has upstream source content changes to review
- `source-missing`: a previously tracked upstream source disappeared
- `up-to-date`: the tracked upstream source set and hashes still match

The generated `_conflicts/conflicts.json` includes these statuses along with the record type (`object`, `preamble`, or `file`).

## Create Manifest

`create` writes `_merged/` review records from a TOML manifest. If `output` is omitted, `source_file` is used as the output path.

```toml
[[records]]
type = "object"
source_file = "common/scripted_triggers/my_feature.txt"
body = '''
my_feature = {
	value = 1
}
'''

[[records]]
type = "preamble"
output = "common/scripted_triggers/my_feature.txt"
body = "@generated = yes"

[[records]]
type = "file"
output = "events/my_feature_note.txt"
body = "generated = full_file"
```

Supported record types are:

- `object`: a standard object block merged into an output file
- `preamble`: file header content placed before object blocks
- `file`: a whole-file passthrough record that becomes the entire output file

## Project config

Projects can provide either:

- an explicit config path via `--config-file`
- a root-level `mod_merger.toml`
- a root-level `.mod-merger.toml`

See [examples/bpvr_patch.toml](/disks/Storage/Code%20Workspaces/Paradox%20Mod%20Merger%20Tool/examples/bpvr_patch.toml) for a concrete configuration.

## Development

Internal module layout:

- `project.py`: config loading and validation
- `parse.py`: descriptor parsing and object-block extraction
- `metadata.py`: merged-record metadata parsing/rendering
- `domain.py`: shared dataclasses for conflicts and records
- `layout.py`: output, snapshot, and path derivation helpers
- `scan.py`: source scanning, conflict detection, snapshots, and seeding
- `create.py`: public manifest-driven record creation API
- `assemble.py`: public assembly API for `_merged/` records
- `generate.py`: implementation for manifest-driven record creation
- `build.py`: implementation for assembling `_merged/` records into `_build/`
- `commands.py`: public command orchestration layer used by the CLI

Run the tests with:

```bash
cd '/disks/Storage/Code Workspaces/Paradox Mod Merger Tool'
PYTHONPATH=src python3 -m unittest discover -s tests -v
```
