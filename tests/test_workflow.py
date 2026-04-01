from __future__ import annotations

import json
import tempfile
import textwrap
import unittest
from pathlib import Path

from paradox_mod_merger_tool.commands import run_assemble, run_create, run_scan
from paradox_mod_merger_tool.metadata import read_leading_metadata_block, render_metadata_block
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
            tracking = "_tracking"

            [templates]
            replace = "{source_dir}/{source_name}_replace_{source_mod_id}.txt"
            merge = "{source_dir}/merged.txt"
            snapshot = "{mod_name}_{source_name}.txt"

            [mods]
            vanilla = ""
            source = "Source Mod"
            my_mod = "_My Patch"

            [conflicts]
            [[conflicts.rules]]
            any_from = ["source"]
            with_any = ["vanilla"]

            [priority]
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

    def test_scan_scopes_conflicts_by_source_path_and_auto_merges_updates(self) -> None:
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
            self.assertEqual(conflicts["items"][0]["source_path"], "common")
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
            self.assertEqual(updated_conflicts["items"][0]["status"], "auto-merged")
            tracking_state = json.loads((root / "_tracking" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(len(tracking_state), 1)
            tracked_item = next(iter(tracking_state.values()))
            self.assertIn("vanilla/common/a.txt", tracked_item["sources"])
            self.assertIn("source/common/a.txt", tracked_item["sources"])

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
            self._write_text(root / "common" / "inline_scripts" / "helpers.txt", "value = 1")
            self._write_text(root / "Source Mod" / "common" / "inline_scripts" / "helpers.txt", "value = 2")
            self._write_text(
                root / "common" / "scripted_effects" / "inline_script_test.txt",
                """
                inline_script = {
                    value = 1
                }
                """,
            )
            self._write_text(
                root / "Source Mod" / "common" / "scripted_effects" / "inline_script_test.txt",
                """
                inline_script = {
                    value = 2
                }
                """,
            )
            self._write_text(
                root / "common" / "scripted_triggers" / "triggered_rules.txt",
                """
                triggered_planet = {
                    value = 1
                }
                """,
            )
            self._write_text(
                root / "Source Mod" / "common" / "scripted_triggers" / "triggered_rules.txt",
                """
                triggered_planet = {
                    value = 2
                }
                """,
            )
            self._write_text(root / "common" / "on_actions" / "hooks.txt", "value = 1")
            self._write_text(root / "Source Mod" / "common" / "on_actions" / "hooks.txt", "value = 2")

            run_scan(project)

            conflicts = json.loads((root / "_conflicts" / "conflicts.json").read_text(encoding="utf-8"))
            kinds = {(item["record_type"], item["source_path"]) for item in conflicts["items"]}
            self.assertIn(("preamble", "common/script_values/rules.txt"), kinds)
            self.assertNotIn(("file", "events/notes.txt"), kinds)
            self.assertIn(("file", "common/inline_scripts/helpers.txt"), kinds)
            self.assertFalse(any(item["name"] == "inline_script" for item in conflicts["items"]))
            self.assertFalse(any(item["name"].startswith("triggered_") for item in conflicts["items"]))
            self.assertFalse(any("on_actions" in item["source_path"] for item in conflicts["items"]))
            self.assertTrue((root / "_merged" / "common" / "script_values" / "rules_replace_source__preamble.txt").exists())
            self.assertFalse((root / "_merged" / "events" / "notes_replace_source__whole_file.txt").exists())

    def test_scan_ignores_identical_object_blocks(self) -> None:
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
                root / "Source Mod" / "common" / "a.txt",
                """
                shared = {
                    value = 1
                }
                """,
            )

            run_scan(project)

            conflicts = json.loads((root / "_conflicts" / "conflicts.json").read_text(encoding="utf-8"))
            self.assertEqual(conflicts["summary"]["total"], 0)

    def test_scan_removes_artifacts_when_conflict_disappears(self) -> None:
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
                root / "Source Mod" / "common" / "a.txt",
                """
                shared = {
                    value = 2
                }
                """,
            )

            run_scan(project)

            merged = root / "_merged" / "common" / "shared.txt"
            vanilla_snapshot = root / "_tracking" / "common" / "a" / "shared" / "vanilla_a.txt"
            source_snapshot = root / "_tracking" / "common" / "a" / "shared" / "source_a.txt"
            self.assertTrue(merged.exists())
            self.assertTrue(vanilla_snapshot.exists())
            self.assertTrue(source_snapshot.exists())

            self._write_text(
                root / "Source Mod" / "common" / "a.txt",
                """
                shared = {
                    value = 1
                }
                """,
            )

            run_scan(project)

            conflicts = json.loads((root / "_conflicts" / "conflicts.json").read_text(encoding="utf-8"))
            self.assertEqual(conflicts["summary"]["total"], 0)
            self.assertFalse(merged.exists())
            self.assertFalse(vanilla_snapshot.exists())
            self.assertFalse(source_snapshot.exists())
            tracking_state = json.loads((root / "_tracking" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(tracking_state, {})

    def test_review_script_only_lists_actionable_conflicts(self) -> None:
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
                root / "Source Mod" / "common" / "a.txt",
                """
                shared = {
                    value = 2
                }
                """,
            )

            run_scan(project)

            first_script = (root / "_conflicts" / "review_conflicts.sh").read_text(encoding="utf-8")
            self.assertIn("status: %s\n' new-upstream", first_script)

            run_scan(project)

            second_script = (root / "_conflicts" / "review_conflicts.sh").read_text(encoding="utf-8")
            self.assertIn("No actionable conflicts.", second_script)
            self.assertNotIn("status: %s\n' up-to-date", second_script)

    def test_scan_filters_vanilla_to_non_vanilla_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project = self._load_project(root)
            self._write_text(
                root / "common" / "shared_rules.txt",
                """
                shared = {
                    value = 1
                }
                """,
            )
            self._write_text(
                root / "Source Mod" / "common" / "shared_rules.txt",
                """
                shared = {
                    value = 2
                }
                """,
            )
            invalid_path = root / "common" / "huge_vanilla_only.txt"
            invalid_path.parent.mkdir(parents=True, exist_ok=True)
            invalid_path.write_bytes(b"\xff\xfe\xfa")

            run_scan(project)

            conflicts = json.loads((root / "_conflicts" / "conflicts.json").read_text(encoding="utf-8"))
            self.assertEqual(conflicts["summary"]["total"], 1)
            self.assertEqual(conflicts["items"][0]["source_path"], "common")

    def test_scan_seeded_object_records_include_supported_version_without_auto_generated_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project = self._load_project(root)
            self._write_text(
                root / "common" / "districts.txt",
                """
                @district_factor = 1.5

                dist_1 = {
                    value = @district_factor
                }

                dist_2 = {
                    value = @district_factor
                }
                """,
            )
            self._write_text(
                root / "Source Mod" / "common" / "districts.txt",
                """
                @district_factor = 2.5

                dist_1 = {
                    value = @district_factor
                }

                dist_2 = {
                    value = @district_factor
                }
                """,
            )

            run_scan(project)

            first = (root / "_merged" / "common" / "dist_1.txt").read_text(encoding="utf-8")
            second = (root / "_merged" / "common" / "dist_2.txt").read_text(encoding="utf-8")
            first_metadata, first_body = read_leading_metadata_block(first)
            second_metadata, second_body = read_leading_metadata_block(second)

            self.assertNotIn("# auto-generated", first)
            self.assertNotIn("# auto-generated", second)
            self.assertEqual(first_metadata.get("supported_version"), "")
            self.assertEqual(second_metadata.get("supported_version"), "")
            self.assertNotIn("upstream_status", first_metadata)
            self.assertNotIn("upstream_status", second_metadata)
            first_sources = first_metadata["sources"]
            second_sources = second_metadata["sources"]
            first_refs = {source["path"] for source in first_sources}
            second_refs = {source["path"] for source in second_sources}
            self.assertEqual(first_refs, {"vanilla/common/districts.txt", "source/common/districts.txt"})
            self.assertEqual(second_refs, {"vanilla/common/districts.txt", "source/common/districts.txt"})
            self.assertIn("dist_1 = {", first_body)
            self.assertNotIn("dist_2 = {", first_body)
            self.assertIn("dist_2 = {", second_body)
            self.assertNotIn("dist_1 = {", second_body)
            self.assertIn("@district_factor = 1.5", first_body)
            self.assertIn("@district_factor = 1.5", second_body)

    def test_scan_removes_upstream_status_from_existing_merged_records(self) -> None:
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
                root / "Source Mod" / "common" / "a.txt",
                """
                shared = {
                    value = 2
                }
                """,
            )

            run_scan(project)

            merged = root / "_merged" / "common" / "shared.txt"
            initial_metadata, _ = read_leading_metadata_block(merged.read_text(encoding="utf-8"))
            self.assertNotIn("upstream_status", initial_metadata)

            # Simulate an old merged record header that still contains upstream_status.
            merged.write_text(
                merged.read_text(encoding="utf-8").replace("# supported_version: ", "# supported_version: \n# upstream_status: stale\n", 1),
                encoding="utf-8",
            )

            self._write_text(
                root / "common" / "a.txt",
                """
                shared = {
                    value = 3
                }
                """,
            )
            run_scan(project)

            updated_metadata, _ = read_leading_metadata_block(merged.read_text(encoding="utf-8"))
            self.assertNotIn("upstream_status", updated_metadata)
            self.assertEqual(updated_metadata.get("supported_version"), "")

    def test_scan_auto_merges_stale_record_with_three_way_merge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project = self._load_project(root)
            self._write_text(
                root / "common" / "a.txt",
                """
                shared = {
                    value = 1
                    mid_1 = 11
                    mid_2 = 12
                    mid_3 = 13
                    mid_4 = 14
                    another = 5
                }
                """,
            )
            self._write_text(
                root / "Source Mod" / "common" / "a.txt",
                """
                shared = {
                    value = 10
                    mid_1 = 11
                    mid_2 = 12
                    mid_3 = 13
                    mid_4 = 14
                    another = 5
                }
                """,
            )

            run_scan(project)

            merged = root / "_merged" / "common" / "shared.txt"
            metadata, body = read_leading_metadata_block(merged.read_text(encoding="utf-8"))
            edited_body = body.replace("\tanother = 5", "\tanother = 42")
            edited_body = edited_body.replace("    another = 5", "    another = 42")
            merged.write_text(
                render_metadata_block(metadata, metadata_line_template=project.metadata_line_template)
                + edited_body
                + "\n",
                encoding="utf-8",
            )

            self._write_text(
                root / "common" / "a.txt",
                """
                shared = {
                    value = 2
                    mid_1 = 11
                    mid_2 = 12
                    mid_3 = 13
                    mid_4 = 14
                    another = 5
                }
                """,
            )

            run_scan(project)

            conflicts = json.loads((root / "_conflicts" / "conflicts.json").read_text(encoding="utf-8"))
            self.assertEqual(conflicts["summary"]["auto-merged"], 1)
            self.assertEqual(conflicts["items"][0]["status"], "auto-merged")
            merged_text = merged.read_text(encoding="utf-8")
            self.assertIn("value = 2", merged_text)
            self.assertIn("another = 42", merged_text)
            review_script = (root / "_conflicts" / "review_conflicts.sh").read_text(encoding="utf-8")
            self.assertIn("status: %s\n' auto-merged", review_script)

    def test_scan_updates_existing_merged_sources_when_new_source_appears(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write_text(
                root / "mod_merger.toml",
                """
                [paths]
                build = "_build"
                merged = "_merged"
                conflicts = "_conflicts"
                tracking = "_tracking"

                [templates]
                replace = "{source_dir}/{source_name}_replace_{source_mod_id}.txt"
                merge = "{source_dir}/merged.txt"
                snapshot = "{mod_name}_{source_name}.txt"

                [mods]
                vanilla = ""
                source = "Source Mod"
                source_two = "Source Mod Two"
                my_mod = "_My Patch"

                [conflicts]
                [[conflicts.rules]]
                any_from = ["source", "source_two"]
                with_any = ["vanilla"]

                [priority]
                vanilla = 0
                source = 1
                source_two = 2
                """,
            )
            self._write_descriptor(root / "_My Patch" / "descriptor.mod", "My Patch")
            self._write_descriptor(root / "Source Mod" / "descriptor.mod", "Source Mod")
            self._write_descriptor(root / "Source Mod Two" / "descriptor.mod", "Source Mod Two")
            project = load_project(project_root=root)

            self._write_text(
                root / "common" / "a.txt",
                """
                shared = {
                    value = 1
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

            merged = root / "_merged" / "common" / "shared.txt"
            initial_metadata, _ = read_leading_metadata_block(merged.read_text(encoding="utf-8"))
            initial_refs = {source["path"] for source in initial_metadata.get("sources", [])}
            self.assertEqual(initial_refs, {"vanilla/common/a.txt", "source/common/a.txt"})

            self._write_text(
                root / "Source Mod Two" / "common" / "a.txt",
                """
                shared = {
                    value = 3
                }
                """,
            )
            run_scan(project)

            updated_metadata, _ = read_leading_metadata_block(merged.read_text(encoding="utf-8"))
            updated_refs = {source["path"] for source in updated_metadata.get("sources", [])}
            self.assertEqual(
                updated_refs,
                {
                    "vanilla/common/a.txt",
                    "source/common/a.txt",
                    "source_two/common/a.txt",
                },
            )

    def test_scan_absolute_vanilla_path_keeps_per_object_vanilla_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "project"
            vanilla_root = Path(tmp_dir) / "vanilla"
            source_root = root / "Imports" / "Planetary Diversity - More Arcologies"
            patch_root = root / "_My Patch"
            patch_root.mkdir(parents=True, exist_ok=True)
            source_root.mkdir(parents=True, exist_ok=True)
            vanilla_root.mkdir(parents=True, exist_ok=True)

            self._write_descriptor(patch_root / "descriptor.mod", "My Patch")
            self._write_descriptor(
                source_root / "descriptor.mod",
                "Planetary Diversity - More Arcologies",
                supported_version="4.3.*",
            )
            self._write_text(
                root / "mod_merger.toml",
                f"""
                [paths]
                build = "_build"
                merged = "_merged"
                conflicts = "_conflicts"
                tracking = "_tracking"

                [templates]
                replace = "{{source_dir}}/{{source_name}}_replace_{{source_mod_id}}.txt"
                merge = "{{source_dir}}/merged.txt"
                snapshot = "{{mod_name}}_{{source_name}}.txt"

                [mods]
                vanilla = "{vanilla_root.as_posix()}"
                pd_arcologies = "Imports/Planetary Diversity - More Arcologies"
                my_mod = "_My Patch"

                [conflicts]
                [[conflicts.rules]]
                any_from = ["pd_arcologies"]
                with_any = ["vanilla"]

                [priority]
                vanilla = 0
                pd_arcologies = 1
                """,
            )

            relative_file = Path("common/districts/00_urban_districts.txt")
            self._write_text(
                vanilla_root / relative_file,
                """
                district_battle_thrall = {
                    vanilla = 1
                }

                district_srw_commercial = {
                    vanilla = 2
                }
                """,
            )
            self._write_text(
                source_root / relative_file,
                """
                district_battle_thrall = {
                    source = 1
                }

                district_srw_commercial = {
                    source = 2
                }
                """,
            )

            project = load_project(project_root=root)
            run_scan(project)

            battle_snapshot = root / "_tracking" / "common" / "districts" / "00_urban_districts" / "district_battle_thrall" / "vanilla_00_urban_districts.txt"
            commercial_snapshot = root / "_tracking" / "common" / "districts" / "00_urban_districts" / "district_srw_commercial" / "vanilla_00_urban_districts.txt"

            self.assertTrue(battle_snapshot.exists())
            self.assertTrue(commercial_snapshot.exists())
            self.assertIn("district_battle_thrall = {", battle_snapshot.read_text(encoding="utf-8"))
            self.assertIn("district_srw_commercial = {", commercial_snapshot.read_text(encoding="utf-8"))
            self.assertNotEqual(battle_snapshot, commercial_snapshot)

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

            generated_record = (root / "_merged" / "common" / "generated" / "generated_object.txt").read_text(encoding="utf-8")
            generated_metadata, _ = read_leading_metadata_block(generated_record)
            self.assertEqual(generated_metadata.get("supported_version"), "")

            generated_output = (root / "_build" / "common" / "generated" / "output.txt").read_text(encoding="utf-8")
            self.assertIn("@generated = yes", generated_output)
            self.assertIn("generated_object = {", generated_output)
            generated_file = (root / "_build" / "events" / "generated_note.txt").read_text(encoding="utf-8")
            self.assertEqual(generated_file, "generated = full_file\n")

    def test_assemble_includes_used_file_variables_once_at_top(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project = self._load_project(root)
            self._write_text(
                root / "common" / "districts.txt",
                """
                @district_factor = 1.5

                dist_1 = {
                    value = @district_factor
                }

                dist_2 = {
                    value = @district_factor
                }
                """,
            )
            self._write_text(
                root / "Source Mod" / "common" / "districts.txt",
                """
                @district_factor = 2.5

                dist_1 = {
                    value = @district_factor
                }

                dist_2 = {
                    value = @district_factor
                }
                """,
            )

            run_scan(project)
            run_assemble(project)

            assembled = (root / "_build" / "common" / "districts_replace_source.txt").read_text(encoding="utf-8")
            self.assertIn("@district_factor = 1.5", assembled)
            self.assertEqual(assembled.count("@district_factor = 1.5"), 1)
            self.assertIn("dist_1 = {", assembled)
            self.assertIn("dist_2 = {", assembled)
            self.assertLess(assembled.index("@district_factor = 1.5"), assembled.index("dist_1 = {"))


if __name__ == "__main__":
    unittest.main()
