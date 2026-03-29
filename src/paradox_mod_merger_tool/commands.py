from __future__ import annotations

import shlex

from .assemble import run_assemble
from .create import run_create
from .layout import snapshot_path
from .project import WorkflowProject
from .scan import collect_conflicts, seed_conflicts, snapshot_conflicts, write_conflicts
from .tracking import write_tracking_state


def write_review_script(project: WorkflowProject, conflicts) -> None:
    lines = [
        "#!/usr/bin/env bash",
        "set -u",
        f"cd {shlex.quote(str(project.root))}",
        "command -v code >/dev/null 2>&1 || { echo 'VS Code CLI not found: install/enable the code shell command first.'; exit 1; }",
        "",
        "# Opens the review record plus source diffs in VS Code.",
        "",
    ]
    for entry in conflicts:
        lines.append(f"printf '\n=== {entry.key.record_type}: {entry.key.source_path} :: {entry.key.name} ===\n'")
        lines.append(f"printf 'status: %s\n' {shlex.quote(entry.status)}")
        lines.append(f"code --reuse-window {shlex.quote(str(entry.merged_path))}")
        for source in entry.sources:
            lines.append(f"printf 'source: %s\n' {shlex.quote(source.ref)}")
            lines.append(
                f"code --reuse-window --diff {shlex.quote(str(snapshot_path(project, source.ref, entry.key)))} {shlex.quote(str(entry.merged_path))}"
            )
        lines.append(f"printf 'after editing, run: git add %s\n' {shlex.quote(str(entry.merged_path))}")
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
    conflicts, tracking_state = collect_conflicts(project)
    write_conflicts(project, conflicts)
    snapshots = snapshot_conflicts(project, conflicts)
    seed_conflicts(project, conflicts, snapshots)
    write_tracking_state(project, tracking_state)
    write_review_script(project, conflicts)
    print("scan: source analysis, snapshots, seeded review records, and review script generation complete")
    return 0


__all__ = ["run_assemble", "run_create", "run_scan"]
