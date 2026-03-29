from __future__ import annotations

import json
import tempfile
import textwrap
import unittest
from pathlib import Path

from paradox_mod_merger_tool.commands import run_assemble, run_create, run_scan
from paradox_mod_merger_tool.project import load_project


class WorkflowIntegrationTests(unittest.TestCase):
    @staticmethod
    def _write_text(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")

    @staticmethod
    def _write_descriptor(path: Path, name: str, version: str = "1.0", supported_version: str = "3.14") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            textwrap.dedent(
                f'''
                name="{name}"
                version="{version}"
                supported_version="{supported_version}"
                remote_file_id="123456"
                '''
            ).strip()
            + "\n",
            encoding="utf-8",
        )

    @classmethod
    def _write_config(cls, root: Path) -> None:
        cls._write_text(
            root / "mod_merger.toml",
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
            """,
        )

    @classmethod
    def _load_project(cls, root: Path):
        cls._write_config(root)
        cls._write_descriptor(root / "_My Patch" / "descriptor.mod", "My Patch")
        cls._write_descriptor(root / "Source Mod" / "descriptor.mod", "Source Mod")
        return load_project(project_root=root)

    def test_scan_scopes_conflicts_by_source_path_and_marks_stale_updates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project = self._load_project(root)
            self._write_text(
                root / "common" / "a.txt",
                """
                shared = {
                    value = 1
                }
                """,
            )
            self._write_text(
                root / "common" / "b.txt",
                """
                shared = {
                    value = 10
                }
                """,
            )
            self._write_text(
                root / "Source Mod" / "common" / "a.txt",
                """
                shared = {
                    value = 2
                }
                """,
            )

            run_scan(project)

            conflicts = json.loads((root / "_conflicts" / "conflicts.json").read_text(encoding="utf-8"))
            self.assertEqual(conflicts["summary"]["total"], 1)
            self.assertEqual(conflicts["items"][0]["source_path"], "common/a.txt")
            self.assertEqual(conflicts["items"][0]["record_type"], "object")
            self.assertEqual(conflicts["items"][0]["status"], "new-upstream")

            merged_seed = root / "_merged" / "common" / "shared.txt"
            self.assertTrue(merged_seed.exists())

            self._write_text(
                root / "common" / "a.txt",
                """
                shared = {
                    value = 3
                }
                """,
            )
            run_scan(project)

            updated_conflicts = json.loads((root / "_conflicts" / "conflicts.json").read_text(encoding="utf-8"))
            self.assertEqual(updated_conflicts["items"][0]["status"], "stale")
            tracking_state = json.loads((root / "_merged" / ".upstream_tracking" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(len(tracking_state), 1)
            tracked_item = next(iter(tracking_state.values()))
            self.assertIn("/common/a.txt", tracked_item["sources"])

    def test_scan_surfaces_preamble_and_whole_file_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project = self._load_project(root)
            self._write_text(
                root / "common" / "script_values" / "rules.txt",
                """
                @threshold = 5

                shared = {
                    value = 1
                }
                """,
            )
            self._write_text(
                root / "Source Mod" / "common" / "script_values" / "rules.txt",
                """
                @threshold = 6

                shared = {
                    value = 2
                }
                """,
            )
            self._write_text(root / "events" / "notes.txt", "alpha = 1")
            self._write_text(root / "Source Mod" / "events" / "notes.txt", "alpha = 2")

            run_scan(project)

            conflicts = json.loads((root / "_conflicts" / "conflicts.json").read_text(encoding="utf-8"))
            kinds = {(item["record_type"], item["source_path"]) for item in conflicts["items"]}
            self.assertIn(("preamble", "common/script_values/rules.txt"), kinds)
            self.assertIn(("file", "events/notes.txt"), kinds)
            self.assertTrue((root / "_merged" / "common" / "script_values" / "rules_replace_source__preamble.txt").exists())
            self.assertTrue((root / "_merged" / "events" / "notes_replace_source__whole_file.txt").exists())

    def test_create_and_assemble_support_object_preamble_and_file_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project = self._load_project(root)
            manifest = root / "create.toml"
            manifest.write_text(
                textwrap.dedent(
                    """
                    [[records]]
                    type = "preamble"
                    output = "common/generated/output.txt"
                    body = "@generated = yes"

                    [[records]]
                    type = "object"
                    source_file = "common/generated/output.txt"
                    body = '''
                    generated_object = {
                        value = 7
                    }
                    '''
                    sort_key = [0, 1, "generated_object"]

                    [[records]]
                    type = "file"
                    output = "events/generated_note.txt"
                    body = "generated = full_file"
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            run_create(project, manifest)
            run_assemble(project)

            generated_output = (root / "_build" / "common" / "generated" / "output.txt").read_text(encoding="utf-8")
            self.assertIn("@generated = yes", generated_output)
            self.assertIn("generated_object = {", generated_output)
            generated_file = (root / "_build" / "events" / "generated_note.txt").read_text(encoding="utf-8")
            self.assertEqual(generated_file, "generated = full_file\n")


if __name__ == "__main__":
    unittest.main()
