from __future__ import annotations

import tempfile
import tomllib
import unittest
from pathlib import Path

from paradox_mod_merger_tool.init import run_init
from paradox_mod_merger_tool.cli import main


class InitTests(unittest.TestCase):
    def _run(
        self,
        root: Path,
        patch_name: str = "My Patch",
        my_mod_dir: str | None = None,
        extra_mods: list[tuple[str, str]] | None = None,
        source_mods: list[str] | None = None,
        filter_mods: list[str] | None = None,
        force: bool = False,
    ) -> int:
        return run_init(
            project_root=root,
            patch_name=patch_name,
            my_mod_dir_rel=my_mod_dir,
            extra_mods=extra_mods or [],
            source_mod_aliases=source_mods or [],
            conflict_filter_mods=filter_mods or [],
            force=force,
        )

    # ------------------------------------------------------------------
    # Config generation

    def test_creates_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rc = self._run(root, patch_name="My Patch")
            self.assertEqual(rc, 0)
            self.assertTrue((root / "mod_merger.toml").exists())

    def test_config_has_required_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._run(root)
            with (root / "mod_merger.toml").open("rb") as fh:
                cfg = tomllib.load(fh)
            self.assertIn("paths", cfg)
            self.assertIn("templates", cfg)
            self.assertIn("mods", cfg)

    def test_config_paths_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._run(root, patch_name="My Patch", my_mod_dir="_patch")
            with (root / "mod_merger.toml").open("rb") as fh:
                cfg = tomllib.load(fh)
            self.assertEqual(cfg["paths"]["build"], "_build")
            self.assertEqual(cfg["paths"]["merged"], "_merged")
            self.assertEqual(cfg["paths"]["conflicts"], "_conflicts")

    def test_vanilla_alias_is_always_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._run(root)
            with (root / "mod_merger.toml").open("rb") as fh:
                cfg = tomllib.load(fh)
            self.assertEqual(cfg["mods"]["vanilla"], "")

    def test_my_mod_alias_is_always_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._run(root, patch_name="Test Patch", my_mod_dir="test_patch")
            with (root / "mod_merger.toml").open("rb") as fh:
                cfg = tomllib.load(fh)
            self.assertEqual(cfg["mods"]["my_mod"], "test_patch")

    def test_extra_mods_appear_in_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._run(
                root,
                extra_mods=[("mod_a", "External Mods/Mod A"), ("mod_b", "External Mods/Mod B")],
            )
            with (root / "mod_merger.toml").open("rb") as fh:
                cfg = tomllib.load(fh)
            self.assertEqual(cfg["mods"]["mod_a"], "External Mods/Mod A")
            self.assertEqual(cfg["mods"]["mod_b"], "External Mods/Mod B")

    def test_source_mods_in_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._run(
                root,
                extra_mods=[("mod_a", "External Mods/Mod A")],
                source_mods=["mod_a"],
                filter_mods=["vanilla"],
            )
            with (root / "mod_merger.toml").open("rb") as fh:
                cfg = tomllib.load(fh)
            self.assertIn("rules", cfg["conflicts"])
            self.assertIn("mod_a", cfg["conflicts"]["rules"][0]["any_from"])

    def test_filter_mods_in_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._run(root, source_mods=["mod_a"], filter_mods=["vanilla"])
            with (root / "mod_merger.toml").open("rb") as fh:
                cfg = tomllib.load(fh)
            self.assertIn("rules", cfg["conflicts"])

    def test_vanilla_has_priority_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._run(root)
            with (root / "mod_merger.toml").open("rb") as fh:
                cfg = tomllib.load(fh)
            self.assertEqual(cfg["priority"]["vanilla"], 0)

    # ------------------------------------------------------------------
    # Directory creation

    def test_working_dirs_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._run(root)
            self.assertTrue((root / "_merged").is_dir())
            self.assertTrue((root / "_build").is_dir())
            self.assertTrue((root / "_conflicts").is_dir())

    def test_my_mod_dir_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._run(root, patch_name="My Patch", my_mod_dir="my_patch_dir")
            self.assertTrue((root / "my_patch_dir").is_dir())

    def test_my_mod_dir_defaults_to_patch_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._run(root, patch_name="Cool Patch")
            self.assertTrue((root / "Cool Patch").is_dir())

    # ------------------------------------------------------------------
    # descriptor.mod creation

    def test_descriptor_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._run(root, patch_name="My Patch", my_mod_dir="my_patch")
            descriptor = root / "my_patch" / "descriptor.mod"
            self.assertTrue(descriptor.exists())

    def test_descriptor_contains_patch_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._run(root, patch_name="Awesome Patch", my_mod_dir="awesome_patch")
            text = (root / "awesome_patch" / "descriptor.mod").read_text(encoding="utf-8")
            self.assertIn("Awesome Patch", text)

    def test_descriptor_not_overwritten_on_second_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._run(root, patch_name="My Patch", my_mod_dir="my_patch")
            descriptor = root / "my_patch" / "descriptor.mod"
            descriptor.write_text("custom content", encoding="utf-8")
            self._run(root, patch_name="My Patch", my_mod_dir="my_patch", force=True)
            self.assertEqual(descriptor.read_text(encoding="utf-8"), "custom content")

    # ------------------------------------------------------------------
    # Guard against accidentally overwriting config

    def test_refuses_to_overwrite_config_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._run(root)
            original = (root / "mod_merger.toml").read_text(encoding="utf-8")
            rc = self._run(root, patch_name="Other Patch")
            self.assertEqual(rc, 1)
            self.assertEqual((root / "mod_merger.toml").read_text(encoding="utf-8"), original)

    def test_force_overwrites_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._run(root, patch_name="First Patch", my_mod_dir="first_patch")
            rc = self._run(root, patch_name="Second Patch", my_mod_dir="second_patch", force=True)
            self.assertEqual(rc, 0)
            with (root / "mod_merger.toml").open("rb") as fh:
                cfg = tomllib.load(fh)
            self.assertEqual(cfg["mods"]["my_mod"], "second_patch")

    # ------------------------------------------------------------------
    # Generate a loadable project config

    def test_generated_config_is_loadable(self) -> None:
        """Config written by init must be parseable by load_project."""
        from paradox_mod_merger_tool.project import load_project

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._run(
                root,
                patch_name="Test Patch",
                my_mod_dir="test_patch",
                extra_mods=[("mod_a", "Mods/Mod A")],
                source_mods=["mod_a"],
                filter_mods=["vanilla"],
            )
            project = load_project(project_root=root)
            self.assertEqual(project.root, root)
            self.assertIn(frozenset(("vanilla", "mod_a")), project.allowed_conflict_pairs)

    # ------------------------------------------------------------------
    # CLI integration

    def test_cli_init_creates_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rc = main([
                "--project-root", str(root),
                "init",
                "--patch-name", "CLI Patch",
                "--patch-dir", "cli_patch",
                "--mod", "mod_x=External Mods/Mod X",
                "--source-mod", "mod_x",
                "--filter-mod", "vanilla",
            ])
            self.assertEqual(rc, 0)
            self.assertTrue((root / "mod_merger.toml").exists())
            with (root / "mod_merger.toml").open("rb") as fh:
                cfg = tomllib.load(fh)
            self.assertEqual(cfg["mods"]["mod_x"], "External Mods/Mod X")

    def test_cli_init_invalid_mod_spec_exits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(SystemExit):
                main([
                    "--project-root", str(root),
                    "init",
                    "--patch-name", "P",
                    "--mod", "no-equals-sign",
                ])


if __name__ == "__main__":
    unittest.main()
