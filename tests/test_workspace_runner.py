from __future__ import annotations

import tempfile
import time
import unittest
from dataclasses import replace
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

    def test_registered_pilot_verifier_runs_by_default(self):
        family = load_case_family(ROOT / "behavior_cases" / "dashboard-filter-refresh" / "family.json")
        condition = ModelCondition(
            provider="deterministic",
            model_id="workspace-registered-verifier",
            adapter_id="test-workspace",
            prompt=family.initial_context["prompt"],
        )

        def adapter(task, tools):
            tools.edit_file("lib/cache.ts", "['metrics']);", "['metrics', range]);")
            tools.stop("patch applied")
            return AgentResult(status="completed")

        with tempfile.TemporaryDirectory() as directory:
            record = run_workspace_trial(
                family,
                family.variants[1],
                condition,
                adapter,
                artifacts_root=Path(directory) / "artifacts",
                workspace_parent=Path(directory) / "workspaces",
                run_id="registered-verifier-run",
            )
        self.assertEqual(record["verifier_result"]["verifier_id"], "dashboard-filter-refresh:cache-key-v1")
        self.assertTrue(record["verifier_result"]["passed"])

    def test_workspace_trial_without_verifier_fails_closed(self):
        family = load_case_family(ROOT / "behavior_cases" / "dashboard-filter-refresh" / "family.json")
        unregistered_variant = replace(family.variants[0], family_id="unregistered-family")
        unregistered_family = replace(
            family,
            family_id="unregistered-family",
            variants=(unregistered_variant,),
        )
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
                unregistered_family,
                unregistered_variant,
                condition,
                adapter,
                artifacts_root=Path(directory) / "artifacts",
                workspace_parent=Path(directory) / "workspaces",
                run_id="no-verifier-run",
            )
        self.assertEqual(record["verifier_result"]["status"], "not_configured")
        self.assertFalse(record["verifier_result"]["passed"])

    def test_budget_rejection_happens_before_workspace_io(self):
        family = load_case_family(ROOT / "behavior_cases" / "dashboard-filter-refresh" / "family.json")
        condition = ModelCondition(
            provider="deterministic",
            model_id="workspace-budget",
            adapter_id="test-workspace",
            prompt=family.initial_context["prompt"],
        )

        def adapter(task, tools):
            for target in family.variants[0].files:
                self.assertTrue(tools.request("inspect", target).accepted)
            rejected = tools.request("inspect", "does-not-exist.ts")
            self.assertFalse(rejected.accepted)
            self.assertEqual(rejected.error, "evidence budget exceeded")
            tools.stop("budget test")
            return AgentResult(status="completed")

        with tempfile.TemporaryDirectory() as directory:
            record = run_workspace_trial(
                family,
                family.variants[0],
                condition,
                adapter,
                artifacts_root=Path(directory) / "artifacts",
                workspace_parent=Path(directory) / "workspaces",
                run_id="budget-run",
            )
        self.assertEqual(record["execution_status"], "completed")

    def test_checkpoint_event_bound_is_enforced(self):
        family = load_case_family(ROOT / "behavior_cases" / "dashboard-filter-refresh" / "family.json")
        bounded_family = replace(family, max_events=2)
        condition = ModelCondition(
            provider="deterministic",
            model_id="workspace-events",
            adapter_id="test-workspace",
            prompt=family.initial_context["prompt"],
        )

        def adapter(task, tools):
            for _ in range(3):
                tools.checkpoint(
                    leading_hypothesis="one",
                    alternative_hypothesis="two",
                    confidence=0.5,
                    changed_by="test",
                    next_action="continue",
                )
            return AgentResult(status="completed")

        with tempfile.TemporaryDirectory() as directory:
            record = run_workspace_trial(
                bounded_family,
                bounded_family.variants[0],
                condition,
                adapter,
                artifacts_root=Path(directory) / "artifacts",
                workspace_parent=Path(directory) / "workspaces",
                run_id="event-run",
            )
        self.assertEqual(record["trace"]["status"], "event_limit")
        self.assertLessEqual(len(record["trace"]["events"]), bounded_family.max_events)

    def test_timeout_skips_verification_and_defers_cleanup(self):
        family = load_case_family(ROOT / "behavior_cases" / "dashboard-filter-refresh" / "family.json")
        condition = ModelCondition(
            provider="deterministic",
            model_id="workspace-timeout",
            adapter_id="test-workspace",
            prompt=family.initial_context["prompt"],
        )
        verified = {"called": False}

        def adapter(task, tools):
            time.sleep(0.15)
            return AgentResult(status="completed")

        def verifier(received_family, received_variant, workspace):
            verified["called"] = True
            return WorkspaceVerifierResult("timeout-v1", "passed", True, {}, [])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = run_workspace_trial(
                family,
                family.variants[0],
                condition,
                adapter,
                artifacts_root=root / "artifacts",
                workspace_parent=root / "workspaces",
                verifier=verifier,
                run_id="timeout-run",
                adapter_timeout_seconds=0.01,
            )
            self.assertEqual(record["execution_status"], "adapter_timeout")
            self.assertTrue(record["infrastructure_censored"])
            self.assertEqual(record["verifier_result"]["status"], "timeout")
            self.assertFalse(record["verifier_result"]["passed"])
            self.assertFalse(verified["called"])
            self.assertTrue(record["workspace_cleanup_deferred"])
            self.assertTrue(list((root / "workspaces").iterdir()))
            time.sleep(0.2)

    def test_materialization_failure_cleans_up_temporary_workspace(self):
        family = load_case_family(ROOT / "behavior_cases" / "dashboard-filter-refresh" / "family.json")
        unsafe = replace(family.variants[0], files={"../outside.ts": "export const bad = true;"})
        condition = ModelCondition(
            provider="deterministic",
            model_id="workspace-materialization-failure",
            adapter_id="test-workspace",
            prompt=family.initial_context["prompt"],
        )

        def adapter(task, tools):
            return AgentResult(status="completed")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                run_workspace_trial(
                    family,
                    unsafe,
                    condition,
                    adapter,
                    artifacts_root=root / "artifacts",
                    workspace_parent=root / "workspaces",
                    run_id="materialization-failure-run",
                )
            self.assertEqual(list((root / "workspaces").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
