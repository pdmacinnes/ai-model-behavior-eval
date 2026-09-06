from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from evidence_eval.runner import AgentResult, ModelCondition
from evidence_eval.schema import load_case_family
from evidence_eval.workspace_grader import WorkspaceVerifierResult
from evidence_eval.workspace_runner import run_workspace_trial


ROOT = Path(__file__).resolve().parents[1]


class WorkspaceRunnerTests(unittest.TestCase):
    def test_trial_materializes_visible_files_and_verifies_after_adapter(self):
        family = load_case_family(ROOT / "behavior_cases" / "dashboard-filter-refresh" / "family.json")
        variant = family.variants[1]
        condition = ModelCondition(
            provider="deterministic",
            model_id="workspace-policy",
            adapter_id="test-workspace",
            prompt=family.initial_context["prompt"],
        )
        seen: dict[str, object] = {}

        def adapter(task, tools):
            self.assertEqual(set(task), set(family.initial_context) | {"tool_contract"})
            response = tools.request("inspect", "lib/cache.ts")
            self.assertTrue(response.accepted)
            self.assertIn("unstable_cache", response.content)
            self.assertNotIn("reveals", response.to_dict())
            tools.checkpoint(
                leading_hypothesis="cache key behavior",
                alternative_hypothesis="query propagation",
                confidence=0.8,
                changed_by="cache inspection",
                next_action="stop",
            )
            tools.stop("evidence collected")
            return AgentResult(status="completed", final_response="The cache key is the next place to investigate.")

        def verifier(received_family, received_variant, workspace):
            seen["family"] = received_family.family_id
            seen["variant"] = received_variant.variant_id
            seen["file"] = (workspace / "lib/cache.ts").is_file()
            return WorkspaceVerifierResult("dashboard-v1", "passed", True, {"visible_files": True}, [])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = run_workspace_trial(
                family,
                variant,
                condition,
                adapter,
                artifacts_root=root / "artifacts",
                workspace_parent=root / "workspaces",
                verifier=verifier,
                run_id="workspace-run",
            )
            self.assertEqual(record["execution_status"], "completed")
            self.assertEqual(record["verifier_result"]["status"], "passed")
            self.assertEqual(seen["family"], family.family_id)
            self.assertTrue(seen["file"])
            self.assertEqual(list((root / "workspaces").iterdir()), [])
            self.assertTrue((root / "artifacts" / "runs" / "workspace-run" / "mutation_observer.json").exists())

    def test_edit_is_observed_before_runner_owned_verification(self):
        family = load_case_family(ROOT / "behavior_cases" / "dashboard-filter-refresh" / "family.json")
        variant = family.variants[1]
        condition = ModelCondition(
            provider="deterministic",
            model_id="workspace-edit",
            adapter_id="test-workspace",
            prompt=family.initial_context["prompt"],
        )
        seen: dict[str, object] = {}

        def adapter(task, tools):
            response = tools.edit_file("lib/cache.ts", "['metrics']);", "['metrics', range]);")
            self.assertTrue(response.accepted)
            tools.stop("patch applied")
            return AgentResult(status="completed", final_response="I updated the cache identity.")

        def verifier(received_family, received_variant, workspace):
            seen["fixed"] = "['metrics', range]" in (workspace / "lib/cache.ts").read_text(encoding="utf-8")
            return WorkspaceVerifierResult("dashboard-v1", "passed", bool(seen["fixed"]), {"cache_key": bool(seen["fixed"])}, [])

        with tempfile.TemporaryDirectory() as directory:
            record = run_workspace_trial(
                family,
                variant,
                condition,
                adapter,
                artifacts_root=Path(directory) / "artifacts",
                workspace_parent=Path(directory) / "workspaces",
                verifier=verifier,
                run_id="edit-run",
            )
            self.assertTrue(seen["fixed"])
            self.assertTrue(record["verifier_result"]["passed"])
            self.assertIn("lib/cache.ts", record["mutation_observer"]["touched_paths"])

    def test_workspace_trial_without_verifier_fails_closed(self):
        family = load_case_family(ROOT / "behavior_cases" / "dashboard-filter-refresh" / "family.json")
        condition = ModelCondition(
            provider="deterministic",
            model_id="workspace-no-verifier",
            adapter_id="test-workspace",
            prompt=family.initial_context["prompt"],
        )

        def adapter(task, tools):
            tools.stop("no verifier test")
            return AgentResult(status="completed")

        with tempfile.TemporaryDirectory() as directory:
            record = run_workspace_trial(
                family,
                family.variants[0],
                condition,
                adapter,
                artifacts_root=Path(directory) / "artifacts",
                workspace_parent=Path(directory) / "workspaces",
                run_id="no-verifier-run",
            )
        self.assertEqual(record["verifier_result"]["status"], "not_configured")
        self.assertFalse(record["verifier_result"]["passed"])


if __name__ == "__main__":
    unittest.main()
