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
python -m pip install -e .
```

## Usage

### Initialising a new project

Run `init` once inside an empty project directory to generate `mod_merger.toml` and the required working directories:

```bash
paradox-mod-merger --project-root /path/to/project init \
  --patch-name "My Compatibility Patch" \
  --mod pd_arcologies="External Mods/Planetary Diversity - More Arcologies" \
  --mod bpvr_base="External Mods/BPVR - More Building Slots" \
  --source-mod pd_arcologies \
  --source-mod bpvr_base \
  --filter-mod vanilla \
  --filter-mod pd_arcologies
```

This creates:

- `mod_merger.toml` — project config with sane defaults you can edit
- `My Compatibility Patch/descriptor.mod` — skeleton mod descriptor
- `_merged/`, `_build/`, `_conflicts/` — working directories

Flags:

| Flag                 | Description                                                      |
|----------------------|------------------------------------------------------------------|
| `--patch-name NAME`  | **(required)** Human-readable name of your patch mod             |
| `--patch-dir PATH`   | Relative directory for the patch mod. Defaults to the patch name |
| `--mod ALIAS=PATH`   | Add a mod alias (repeat for each mod)                            |
| `--source-mod ALIAS` | Mark an alias as a conflict-source mod (repeat as needed)        |
| `--filter-mod ALIAS` | Mark an alias as a conflict-filter mod (repeat as needed)        |
| `--force`            | Overwrite an existing `mod_merger.toml`                          |

After running `init`, open `mod_merger.toml` to verify the paths match your actual mod layout, then run `scan`.

### Typical command sequence

Run the workflow in this order:

```bash
paradox-mod-merger --project-root /path/to/project scan
# review and resolve files in _merged/ (if present)
# bash _conflicts/review_conflicts.sh
paradox-mod-merger --project-root /path/to/project assemble
paradox-mod-merger --project-root /path/to/project create --manifest-file /path/to/project/create.toml
```

Use `create` only when you are generating new review records from a manifest.

### Other commands

With an installed console script:

```bash
paradox-mod-merger --project-root /path/to/project --config-file /path/to/project/.scripts/project-config.toml scan
paradox-mod-merger --project-root /path/to/project --config-file /path/to/project/.scripts/project-config.toml assemble
paradox-mod-merger --project-root /path/to/project --config-file /path/to/project/.scripts/project-config.toml create --manifest-file /path/to/project/.scripts/create.toml
```

Using the module entrypoint:

```bash
cd '/disks/Storage/Code Workspaces/Paradox Mod Merger Tool'
python -m paradox_mod_merger_tool --project-root /path/to/project --config-file /path/to/project/.scripts/project-config.toml scan
python -m paradox_mod_merger_tool --project-root /path/to/project --config-file /path/to/project/.scripts/project-config.toml assemble
python -m paradox_mod_merger_tool --project-root /path/to/project --config-file /path/to/project/.scripts/project-config.toml create --manifest-file /path/to/project/.scripts/create.toml
```

## Scan Output

`scan` keeps `_tracking/state.json` between runs and records a status for each conflict entry:

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
- `init.py`: project initialisation (config scaffold, directory creation)
- `scan.py`: source scanning, conflict detection, snapshots, and seeding
- `create.py`: public manifest-driven record creation API
- `assemble.py`: public assembly API for `_merged/` records
- `generate.py`: implementation for manifest-driven record creation
- `build.py`: implementation for assembling `_merged/` records into `_build/`
- `commands.py`: public command orchestration layer used by the CLI

Run the tests with:

```bash
cd '/disks/Storage/Code Workspaces/Paradox Mod Merger Tool'
python -m unittest discover -s tests -v
```
