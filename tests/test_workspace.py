from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
import os
from pathlib import Path

from evidence_eval.schema import load_case_family
from evidence_eval.workspace import WorkspaceMaterializationError, materialize_variant


ROOT = Path(__file__).resolve().parents[1]


class WorkspaceMaterializationTests(unittest.TestCase):
    def test_materializer_writes_only_visible_variant_files(self):
        family = load_case_family(ROOT / "behavior_cases" / "dashboard-filter-refresh" / "family.json")
        variant = family.variants[0]

        with tempfile.TemporaryDirectory() as directory:
            materialized = materialize_variant(variant, Path(directory) / "workspace")

            self.assertEqual(set(materialized.files), set(variant.files))
            self.assertTrue(materialized.manifest_sha256)
            self.assertFalse((materialized.root / "hidden_cause").exists())
            self.assertFalse((materialized.root / "verifier.json").exists())
            self.assertEqual(
                (materialized.root / "app/dashboard/page.tsx").read_text(encoding="utf-8"),
                variant.files["app/dashboard/page.tsx"],
            )

    def test_materializer_rejects_non_empty_destination(self):
        family = load_case_family(ROOT / "behavior_cases" / "dashboard-filter-refresh" / "family.json")
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "workspace"
            destination.mkdir()
            (destination / "unrelated.txt").write_text("keep", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                materialize_variant(family.variants[0], destination)

    def test_materializer_rejects_paths_that_escape_destination(self):
        family = load_case_family(ROOT / "behavior_cases" / "dashboard-filter-refresh" / "family.json")
        unsafe = replace(family.variants[0], files={"../outside.ts": "export const bad = true;"})
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(WorkspaceMaterializationError):
                materialize_variant(unsafe, Path(directory) / "workspace")

    def test_materializer_rejects_symlink_destination_and_target(self):
        family = load_case_family(ROOT / "behavior_cases" / "dashboard-filter-refresh" / "family.json")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real_destination = root / "real"
            real_destination.mkdir()
            linked_destination = root / "linked"
            try:
                os.symlink(real_destination, linked_destination, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable")
            with self.assertRaises(WorkspaceMaterializationError):
                materialize_variant(family.variants[0], linked_destination)

            linked_parent_target = root / "parent-target"
            linked_parent_target.mkdir()
            linked_parent = root / "parent-link"
            os.symlink(linked_parent_target, linked_parent, target_is_directory=True)
            with self.assertRaises(WorkspaceMaterializationError):
                materialize_variant(family.variants[0], linked_parent / "workspace")


if __name__ == "__main__":
    unittest.main()
