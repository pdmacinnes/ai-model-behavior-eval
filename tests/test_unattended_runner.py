from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cursor_eval.artifacts import ArtifactExistsError

from evidence_eval.runner import AgentResult, ModelCondition, run_unattended_trial
from evidence_eval.schema import load_case_family


ROOT = Path(__file__).resolve().parents[1]


class UnattendedRunnerTests(unittest.TestCase):
    def test_runner_records_condition_trace_and_annotations_once(self):
        family = load_case_family(ROOT / "behavior_cases" / "dashboard-filter-refresh" / "family.json")
        condition = ModelCondition(
            provider="deterministic",
            model_id="trace-first",
            adapter_id="test-policy",
            prompt=family.initial_context["prompt"],
        )

        def adapter(task, tools):
            self.assertEqual(set(task), set(family.initial_context))
            self.assertFalse(hasattr(tools, "_session"))
            response = tools.request("trace", "metrics-request")
            self.assertTrue(response.accepted)
            self.assertNotIn("reveals", response.to_dict())
            tools.checkpoint(
                leading_hypothesis="query propagation",
                alternative_hypothesis="cache key behavior",
                confidence=0.6,
                changed_by="request trace",
                next_action="stop",
            )
            tools.stop("evidence collected")
            return AgentResult(status="completed", final_response="The request boundary is the next place to inspect.")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = run_unattended_trial(
                family,
                family.variants[0],
                condition,
                adapter,
                artifacts_root=root,
                run_id="proof-run",
            )
            self.assertEqual(record["run_id"], "proof-run")
            self.assertEqual(record["protocol_version"], "evidence-protocol-v1")
            self.assertIn("task_hash", record)
            self.assertEqual(record["trace"]["status"], "stopped")
            self.assertEqual(record["behavioral_annotations"]["first_action"], "trace")
            self.assertTrue((root / "runs" / "proof-run" / "immutable.complete").exists())
            self.assertTrue((root / "runs" / "proof-run" / "task.json").exists())
            with self.assertRaises(ArtifactExistsError):
                run_unattended_trial(
                    family,
                    family.variants[0],
                    condition,
                    adapter,
                    artifacts_root=root,
                    run_id="proof-run",
                )

    def test_adapter_failure_is_recorded_without_approval_prompt(self):
        family = load_case_family(ROOT / "behavior_cases" / "dashboard-filter-refresh" / "family.json")
        condition = ModelCondition(
            provider="deterministic",
            model_id="failing-adapter",
            adapter_id="test-policy",
            prompt=family.initial_context["prompt"],
        )

        def adapter(task, tools):
            tools.request("unsupported", "target")
            raise RuntimeError("simulated adapter failure")

        with tempfile.TemporaryDirectory() as directory:
            record = run_unattended_trial(
                family,
                family.variants[0],
                condition,
                adapter,
                artifacts_root=Path(directory),
                run_id="failure-run",
            )
            self.assertEqual(record["execution_status"], "adapter_error")
            self.assertEqual(record["trace"]["events"][0]["kind"], "rejected_action")
            self.assertEqual(record["trace"]["events"][-1]["kind"], "stop")


if __name__ == "__main__":
    unittest.main()
