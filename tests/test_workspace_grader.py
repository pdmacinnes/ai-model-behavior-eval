from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from evidence_eval.schema import load_case_family
from evidence_eval.workspace_grader import (
    WorkspaceVerifierResult,
    invoke_workspace_verifier,
)


ROOT = Path(__file__).resolve().parents[1]


class WorkspaceGraderTests(unittest.TestCase):
    def test_missing_verifier_fails_closed(self):
        family = load_case_family(ROOT / "behavior_cases" / "dashboard-filter-refresh" / "family.json")
        with tempfile.TemporaryDirectory() as directory:
            result = invoke_workspace_verifier(None, family, family.variants[0], Path(directory))
        self.assertEqual(result.status, "not_configured")
        self.assertFalse(result.passed)

    def test_verifier_is_separate_from_authoring_fixture(self):
        family = load_case_family(ROOT / "behavior_cases" / "dashboard-filter-refresh" / "family.json")
        seen: dict[str, object] = {}

        def verifier(received_family, received_variant, workspace):
            seen["family"] = received_family.family_id
            seen["variant"] = received_variant.variant_id
            seen["workspace"] = workspace
            return WorkspaceVerifierResult("test-v1", "passed", True, {"ok": True}, [])

        with tempfile.TemporaryDirectory() as directory:
            result = invoke_workspace_verifier(verifier, family, family.variants[0], Path(directory))
        self.assertTrue(result.passed)
        self.assertEqual(seen["family"], family.family_id)
        self.assertEqual(seen["variant"], family.variants[0].variant_id)


if __name__ == "__main__":
    unittest.main()
