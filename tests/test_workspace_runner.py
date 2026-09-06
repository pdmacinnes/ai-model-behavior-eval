from __future__ import annotations

import tempfile
import time
import unittest
from dataclasses import replace
import os
from pathlib import Path

from evidence_eval.runner import AgentResult, ModelCondition
from evidence_eval.schema import load_case_family
from evidence_eval.workspace_grader import WorkspaceVerifierResult
from evidence_eval.workspace import materialize_variant
from evidence_eval.workspace_runner import _WorkspaceSession, run_workspace_trial


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
            self.assertEqual(set(task), set(family.initial_context) | {"tool_contract", "model_condition"})
            self.assertEqual(
                task["model_condition"],
                {
                    "provider": "deterministic",
                    "model_id": "workspace-policy",
                    "adapter_id": "test-workspace",
                    "reasoning_effort": None,
                },
            )
            for forbidden in ("workspace", "variant_id", "hidden_cause", "verifier", "calibration"):
                self.assertNotIn(forbidden, task)
            inventory = tools.request("list_files", ".")
            self.assertTrue(inventory.accepted)
            self.assertEqual(set(inventory.content.splitlines()), set(variant.files))
            self.assertNotIn("unstable_cache", inventory.content)
            response = tools.request("inspect", "lib/cache.ts")
            self.assertTrue(response.accepted)
            self.assertIn("unstable_cache", response.content)
            self.assertNotEqual(response.content, variant.observation_for("inspect", "lib/cache.ts").content)
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
            self.assertFalse(record["behavioral_annotations"]["repair_attempted"])
            self.assertEqual(record["behavioral_annotations"]["edit_count"], 0)
            self.assertEqual(record["behavioral_annotations"]["termination_reason"], "evidence collected")
            self.assertFalse(record["behavioral_annotations"]["budget_exhausted"])
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

    def test_dashboard_variants_can_apply_declared_repairs_within_budget(self):
        family = load_case_family(ROOT / "behavior_cases" / "dashboard-filter-refresh" / "family.json")
        condition = ModelCondition(
            provider="deterministic",
            model_id="workspace-calibration",
            adapter_id="test-workspace",
            prompt=family.initial_context["prompt"],
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for variant in family.variants:
                def adapter(task, tools, current_variant=variant):
                    inventory = tools.request("list_files", ".")
                    self.assertTrue(inventory.accepted)
                    if current_variant.variant_id == "query-omitted":
                        self.assertTrue(tools.request("trace", "metrics-request").accepted)
                        self.assertTrue(tools.request("inspect", "app/dashboard/page.tsx").accepted)
                        self.assertTrue(tools.request("inspect", "lib/fetchMetrics.ts").accepted)
                        self.assertTrue(
                            tools.edit_file(
                                "app/dashboard/page.tsx",
                                "await getMetrics()",
                                "await getMetrics(params.range)",
                            ).accepted
                        )
                        self.assertTrue(
                            tools.edit_file(
                                "lib/fetchMetrics.ts",
                                "export async function getMetrics() {\n  return fetch('/api/metrics', { cache: 'no-store' }).then((response) => response.json());\n}\n",
                                "export async function getMetrics(range: string) {\n  return fetch(`/api/metrics?range=${range}`, { cache: 'no-store' }).then((response) => response.json());\n}\n",
                            ).accepted
                        )
                    else:
                        self.assertTrue(tools.request("trace", "metrics-request").accepted)
                        self.assertTrue(tools.request("inspect", "lib/cache.ts").accepted)
                        self.assertTrue(tools.edit_file("lib/cache.ts", "['metrics']);", "['metrics', range]);").accepted)
                    tools.stop("declared repair applied")
                    return AgentResult(status="completed", final_response="The declared repair was applied.")

                record = run_workspace_trial(
                    family,
                    variant,
                    condition,
                    adapter,
                    artifacts_root=root / "artifacts",
                    workspace_parent=root / "workspaces",
                    run_id=f"calibration-{variant.variant_id}",
                )
                self.assertTrue(record["verifier_result"]["passed"], variant.variant_id)
                self.assertTrue(record["behavioral_annotations"]["repair_attempted"])
                self.assertGreaterEqual(record["behavioral_annotations"]["edit_count"], 1)

    def test_list_files_rejects_invalid_target_and_bound(self):
        family = load_case_family(ROOT / "behavior_cases" / "dashboard-filter-refresh" / "family.json")
        bounded_family = replace(family, max_response_chars=4)
        condition = ModelCondition(
            provider="deterministic",
            model_id="workspace-list-files-bounds",
            adapter_id="test-workspace",
            prompt=family.initial_context["prompt"],
        )

        def adapter(task, tools):
            invalid = tools.request("list_files", "app")
            self.assertFalse(invalid.accepted)
            self.assertEqual(invalid.error, "list_files target must be '.'")
            bounded = tools.request("list_files", ".")
            self.assertFalse(bounded.accepted)
            self.assertEqual(bounded.error, "tool output bound exceeded")
            tools.stop("list files bounds tested")
            return AgentResult(status="completed")

        with tempfile.TemporaryDirectory() as directory:
            record = run_workspace_trial(
                bounded_family,
                bounded_family.variants[0],
                condition,
                adapter,
                artifacts_root=Path(directory) / "artifacts",
                workspace_parent=Path(directory) / "workspaces",
                run_id="list-files-bounds",
            )
        self.assertFalse(record["behavioral_annotations"]["budget_exhausted"])

    def test_list_files_skips_symlinked_entries(self):
        family = load_case_family(ROOT / "behavior_cases" / "dashboard-filter-refresh" / "family.json")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            materialize_variant(family.variants[0], workspace)
            external = root / "external"
            external.mkdir()
            (external / "secret.ts").write_text("export const secret = true;", encoding="utf-8")
            try:
                os.symlink(external, workspace / "linked", target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable")
            session = _WorkspaceSession(family, family.variants[0], workspace)
            response = session.request("list_files", ".")
            self.assertTrue(response.accepted)
            self.assertNotIn("linked", response.content)
            self.assertNotIn("secret.ts", response.content)

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
        family = replace(
            load_case_family(ROOT / "behavior_cases" / "dashboard-filter-refresh" / "family.json"),
            max_cost=5,
        )
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

    def test_parent_timeout_terminates_adapter_when_supported(self):
        family = load_case_family(ROOT / "behavior_cases" / "dashboard-filter-refresh" / "family.json")
        condition = ModelCondition(
            provider="deterministic",
            model_id="workspace-parent-timeout",
            adapter_id="test-workspace",
            prompt=family.initial_context["prompt"],
        )
        terminated = {"called": False}

        def adapter(task, tools):
            while not terminated["called"]:
                time.sleep(0.005)
            return AgentResult(status="completed")

        def terminate():
            terminated["called"] = True

        adapter.terminate = terminate

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = run_workspace_trial(
                family,
                family.variants[0],
                condition,
                adapter,
                artifacts_root=root / "artifacts",
                workspace_parent=root / "workspaces",
                run_id="parent-timeout-run",
                adapter_timeout_seconds=0.01,
            )
            self.assertTrue(terminated["called"])
            self.assertEqual(record["execution_status"], "adapter_timeout")
            self.assertTrue(record["infrastructure_censored"])
            self.assertFalse(record["workspace_cleanup_deferred"])
            self.assertEqual(record["workspace_cleanup_reason"], "adapter_terminated_after_timeout")
            self.assertEqual(list((root / "workspaces").iterdir()), [])

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
