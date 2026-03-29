from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from paradox_mod_merger_tool.project import load_project


class ProjectTests(unittest.TestCase):
    @staticmethod
    def _write_config(config_path: Path) -> None:
        config_path.write_text(
            textwrap.dedent(
                """
                [paths]
                build = "_build"
                merged = "_merged"
                conflicts = "_conflicts"
                tracking = "_merged/.upstream_tracking"
                patch = "_My Patch"

                [templates]
                replace = "{source_dir}/{source_name}_replace_{source_mod_id}.txt"
                merge = "{source_dir}/merged.txt"
                snapshot = "{mod_name}_{source_name}.txt"

                [mods]
                source_mod_aliases = ["source"]
                conflict_filter_source_mods = ["vanilla", "source"]

                [mods.aliases]
                vanilla = ""
                source = "Source Mod"
                my_patch = "_My Patch"

                [mods.priority]
                vanilla = 0
                source = 1
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )

    def test_load_project_builds_paths_and_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            config_path = root / "mod_merger.toml"
            self._write_config(config_path)
            project = load_project(project_root=root)
            self.assertEqual(project.build_dir, root / "_build")
            self.assertEqual(project.conflicts_dir, root / "_conflicts")
            self.assertEqual(project.alias_to_path["source"], "Source Mod")
            self.assertEqual(project.path_to_alias["Source Mod"], "source")
            self.assertEqual(project.patch_mod, "_My Patch")

    def test_explicit_config_does_not_change_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "project"
            config_root = Path(tmp_dir) / "config"
            root.mkdir()
            config_root.mkdir()
            config_path = config_root / "project-config.toml"
            self._write_config(config_path)
            project = load_project(project_root=root, config_file=config_path)
            self.assertEqual(project.root, root)
            self.assertEqual(project.config_path, config_path)
            self.assertEqual(project.build_dir, root / "_build")


if __name__ == "__main__":
    unittest.main()
