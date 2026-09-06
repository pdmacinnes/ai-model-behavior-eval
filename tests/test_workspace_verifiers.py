from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from evidence_eval.fixtures import apply_declared_mutation
from evidence_eval.schema import load_case_family
from evidence_eval.workspace import materialize_variant
from evidence_eval.workspace_grader import invoke_workspace_verifier
from evidence_eval.workspace_verifiers import registered_workspace_verifier


ROOT = Path(__file__).resolve().parents[1]


class PilotWorkspaceVerifierTests(unittest.TestCase):
    def test_each_registered_verifier_rejects_before_and_accepts_declared_fix(self):
        for path in sorted((ROOT / "behavior_cases").glob("*/family.json")):
            family = load_case_family(path)
            verifier = registered_workspace_verifier(family)
            self.assertIsNotNone(verifier)
            for variant in family.variants:
                with self.subTest(family=family.family_id, variant=variant.variant_id):
                    fixed_files, _ = apply_declared_mutation(variant)
                    fixed_variant = replace(variant, files=fixed_files)
                    with tempfile.TemporaryDirectory() as directory:
                        root = Path(directory)
                        before_root = root / "before"
                        after_root = root / "after"
                        materialize_variant(variant, before_root)
                        materialize_variant(fixed_variant, after_root)
                        before = invoke_workspace_verifier(verifier, family, variant, before_root)
                        after = invoke_workspace_verifier(verifier, family, fixed_variant, after_root)
                    self.assertFalse(before.passed)
                    self.assertTrue(after.passed)


if __name__ == "__main__":
    unittest.main()
