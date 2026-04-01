from __future__ import annotations

import os
import shlex
from pathlib import Path

from .assemble import run_assemble
from .create import run_create
from .init import run_init
from .layout import snapshot_path
from .project import WorkflowProject
from .scan import auto_merge_conflicts, cleanup_retired_conflicts, collect_conflicts, seed_conflicts, snapshot_conflicts, write_conflicts
from .tracking import write_tracking_state


ACTIONABLE_REVIEW_STATUSES = {"new-upstream", "stale", "source-missing", "auto-merged"}


def write_review_script(project: WorkflowProject, conflicts) -> None:
    def to_project_relative(path) -> str:
        try:
            return path.relative_to(project.root).as_posix()
        except ValueError:
            return str(path)

    root_from_script = Path(os.path.relpath(project.root, project.conflicts_dir)).as_posix()

    lines = [
        "#!/usr/bin/env bash",
        "set -u",
        "script_dir=$(cd -- \"$(dirname -- \"${BASH_SOURCE[0]}\")\" && pwd)",
        f"cd -- \"$script_dir/{root_from_script}\"",
        "command -v code >/dev/null 2>&1 || { echo 'VS Code CLI not found: install/enable the code shell command first.'; exit 1; }",
        "",
        "# Opens the review record plus source diffs in VS Code.",
        "",
    ]
    actionable_conflicts = [entry for entry in conflicts if entry.status in ACTIONABLE_REVIEW_STATUSES]

    if not actionable_conflicts:
        lines.append("printf 'No actionable conflicts. Upstream matches your current merged records.\n'")
        lines.append("")

    for entry in actionable_conflicts:
        merged_rel = to_project_relative(entry.merged_path)
        lines.append(f"printf '\n=== {entry.key.record_type}: {entry.key.source_path} :: {entry.key.name} ===\n'")
        lines.append(f"printf 'status: %s\n' {shlex.quote(entry.status)}")
        lines.append(f"code --reuse-window {shlex.quote(merged_rel)}")
        for source in entry.sources[::-1]:
            snapshot_rel = to_project_relative(snapshot_path(project, source.ref, entry.key))
            lines.append(f"printf 'source: %s\n' {shlex.quote(source.ref)}")
            lines.append(
                f"code --reuse-window --diff {shlex.quote(snapshot_rel)} {shlex.quote(merged_rel)}"
            )
        lines.append(f"printf 'after editing, run: git add %s\n' {shlex.quote(merged_rel)}")
        lines.append("read -r -p 'Press Enter for the next record...' _")
        lines.append("")
    lines.extend([
        "printf '\n=== after all files are resolved ===\n'",
        "printf 'run your assemble command for this project\n'",
        "",
    ])
    project.conflicts_dir.mkdir(parents=True, exist_ok=True)
    path = project.conflicts_dir / "review_conflicts.sh"
    path.write_text("\n".join(lines), encoding="utf-8")
    path.chmod(0o755)
    print(f"wrote: {path.relative_to(project.root)}")
    print(f"run: bash {path.relative_to(project.root)}")


def run_scan(project: WorkflowProject) -> int:
    conflicts, tracking_state, previous_state = collect_conflicts(project)
    snapshots = snapshot_conflicts(project, conflicts)
    seed_conflicts(project, conflicts, snapshots)
    conflicts = auto_merge_conflicts(project, conflicts)
    write_conflicts(project, conflicts)
    cleanup_retired_conflicts(project, previous_state, tracking_state)
    write_tracking_state(project, tracking_state)
    write_review_script(project, conflicts)
    print("scan: source analysis, snapshots, seeded review records, and review script generation complete")
    return 0


__all__ = ["run_assemble", "run_create", "run_init", "run_scan"]
