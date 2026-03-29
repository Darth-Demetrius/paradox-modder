from __future__ import annotations

import shutil
from pathlib import Path

from .domain import ConflictKey
from .parse import parse_mod_name
from .project import WorkflowProject


def split_ref(project: WorkflowProject, ref: str) -> tuple[str, str]:
    for mod_name in sorted(project.mods_to_check, key=len, reverse=True):
        prefix = f"{mod_name}/"
        if ref.startswith(prefix):
            return mod_name, ref[len(prefix):]
    raise ValueError(f"Unrecognized ref mod prefix: {ref}")


def derive_output_from_refs(project: WorkflowProject, refs: list[str]) -> str:
    source_mods_in_refs = {
        mod_name for ref in refs if (mod_name := split_ref(project, ref)[0]) in project.source_mods
    }
    if len(source_mods_in_refs) == 1:
        source_mod = source_mods_in_refs.pop()
        source_ref = next(ref for ref in refs if split_ref(project, ref)[0] == source_mod)
        _, rel_path = split_ref(project, source_ref)
        rel = Path(rel_path)
        return project.file_replace_template.format(
            source_dir=rel.parent.as_posix(),
            source_name=rel.stem,
            source_mod_id=project.source_mods[source_mod],
        )
    _, rel_path = split_ref(project, refs[0])
    return project.file_merge_template.format(source_dir=Path(rel_path).parent.as_posix())


def snapshot_path(project: WorkflowProject, ref: str, key: ConflictKey) -> Path:
    mod_name, rel_text = split_ref(project, ref)
    rel = Path(rel_text)
    name = project.snapshot_name_template.format(mod_name=mod_name, source_name=rel.stem)
    scope = key.name if key.record_type == "object" else key.record_type
    return project.tracking_dir / rel.parent / rel.stem / scope / name


def merged_path(project: WorkflowProject, output_rel: str, key: ConflictKey) -> Path:
    output_path = Path(output_rel)
    if key.record_type == "object":
        file_name = f"{key.name}.txt"
    elif key.record_type == "preamble":
        file_name = f"{output_path.stem}__preamble.txt"
    else:
        file_name = f"{output_path.stem}__whole_file.txt"
    return project.merged_dir / output_path.parent / file_name


def active_build_dir(project: WorkflowProject) -> Path:
    return project.build_dir.resolve() if project.build_dir.is_symlink() else project.build_dir


def copy_patch_metadata(project: WorkflowProject, build_dir: Path) -> None:
    mod_name = parse_mod_name(project.patch_dir, project.descriptor_re)
    descriptor_src = project.patch_dir / "descriptor.mod"
    if descriptor_src.exists():
        shutil.copy2(descriptor_src, build_dir / f"{mod_name}.mod")
    for path in project.patch_dir.rglob("*"):
        if path.is_file() and path.suffix == ".md":
            out = build_dir / path.relative_to(project.patch_dir)
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, out)
