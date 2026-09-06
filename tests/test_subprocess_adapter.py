from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from evidence_eval.runner import AgentResult, ModelCondition
from evidence_eval.schema import load_case_family
from evidence_eval.subprocess_adapter import SubprocessAdapterConfig, SubprocessWorkspaceAdapter
from evidence_eval.workspace_grader import WorkspaceVerifierResult
from evidence_eval.workspace_runner import run_workspace_trial


ROOT = Path(__file__).resolve().parents[1]


class SubprocessAdapterTests(unittest.TestCase):
    def test_worker_uses_jsonl_tools_without_receiving_workspace_path(self):
        family = load_case_family(ROOT / "behavior_cases" / "dashboard-filter-refresh" / "family.json")
        condition = ModelCondition(
            provider="deterministic",
            model_id="subprocess-worker",
            adapter_id="jsonl-test-worker",
            prompt=family.initial_context["prompt"],
        )
        worker = "\n".join([
            "import json, sys",
            "task = json.loads(sys.stdin.readline())",
            "assert 'workspace' not in task",
            "print(json.dumps({'type': 'call', 'id': 'edit-1', 'method': 'edit_file', 'arguments': {'path': 'lib/cache.ts', 'before': \"['metrics']);\", 'after': \"['metrics', range]);\"}}), flush=True)",
            "reply = json.loads(sys.stdin.readline())",
            "print(json.dumps({'type': 'call', 'id': 'stop-1', 'method': 'stop_investigation', 'arguments': {'reason': 'worker complete'}}), flush=True)",
            "json.loads(sys.stdin.readline())",
            "print(json.dumps({'type': 'final', 'status': 'completed', 'final_response': 'patched', 'metadata': {'edit_ok': reply['result']['accepted']}}), flush=True)",
        ])
        adapter = SubprocessWorkspaceAdapter(SubprocessAdapterConfig((sys.executable, "-c", worker), timeout_seconds=5.0))

        with tempfile.TemporaryDirectory() as directory:
            record = run_workspace_trial(
                family,
                family.variants[1],
                condition,
                adapter,
                artifacts_root=Path(directory) / "artifacts",
                workspace_parent=Path(directory) / "workspaces",
                run_id="subprocess-run",
            )
        self.assertEqual(record["execution_status"], "completed")
        self.assertTrue(record["verifier_result"]["passed"])
        self.assertEqual(record["adapter_result"]["metadata"]["edit_ok"], True)

    def test_subprocess_timeout_is_censored_without_verification(self):
        family = load_case_family(ROOT / "behavior_cases" / "dashboard-filter-refresh" / "family.json")
        condition = ModelCondition(
            provider="deterministic",
            model_id="subprocess-timeout",
            adapter_id="jsonl-timeout-worker",
            prompt=family.initial_context["prompt"],
        )
        worker = "import time; time.sleep(0.2)"
        adapter = SubprocessWorkspaceAdapter(SubprocessAdapterConfig((sys.executable, "-c", worker), timeout_seconds=0.01))
        verified = {"called": False}

        def verifier(received_family, received_variant, workspace):
            verified["called"] = True
            return WorkspaceVerifierResult("should-not-run", "passed", True, {}, [])

        with tempfile.TemporaryDirectory() as directory:
            record = run_workspace_trial(
                family,
                family.variants[0],
                condition,
                adapter,
                artifacts_root=Path(directory) / "artifacts",
                workspace_parent=Path(directory) / "workspaces",
                verifier=verifier,
                run_id="subprocess-timeout-run",
                adapter_timeout_seconds=5.0,
            )
        self.assertEqual(record["execution_status"], "adapter_timeout")
        self.assertTrue(record["infrastructure_censored"])
        self.assertEqual(record["verifier_result"]["status"], "timeout")
        self.assertFalse(verified["called"])


if __name__ == "__main__":
    unittest.main()
