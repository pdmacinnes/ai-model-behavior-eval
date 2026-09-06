from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_release_builder():
    path = ROOT / "scripts" / "build_public_behavior_release.py"
    spec = importlib.util.spec_from_file_location("public_release_builder", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load public release builder")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PublicReleaseTests(unittest.TestCase):
    def test_release_builder_sanitizes_real_artifact_tree(self):
        builder = _load_release_builder()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts = root / "artifacts" / "runs" / "run-1"
            artifacts.mkdir(parents=True)
            batch = root / "artifacts" / "batches" / "batch-1"
            batch.mkdir(parents=True)
            (batch / "manifest.json").write_text(
                json.dumps({"schema": "evidence-bounded-debugging-batch-v1", "batch_id": "batch-1"}),
                encoding="utf-8",
            )
            (artifacts / "run.json").write_text(
                json.dumps({"variant_id": "secret", "verifier_result": {"status": "declarative_only", "declaration": {"expected_cause": "secret"}}}),
                encoding="utf-8",
            )
            (artifacts / "event_trace.json").write_text(
                json.dumps({"variant_id": "secret", "events": [{"reveals": ["secret"]}]}),
                encoding="utf-8",
            )
            (artifacts / "behavioral_annotations.json").write_text(
                json.dumps(
                    {
                        "revealed_factors": ["secret"],
                        "first_action": "trace",
                        "repair_attempted": False,
                        "edit_count": 0,
                        "termination_reason": "evidence collected",
                        "budget_exhausted": False,
                    }
                ),
                encoding="utf-8",
            )
            (artifacts / "adapter_result.json").write_text(
                json.dumps({"status": "completed", "final_response": "provider output with sk-test-secret"}),
                encoding="utf-8",
            )
            (artifacts / "final_response.txt").write_text("provider output with sk-test-secret", encoding="utf-8")

            output = root / "public"
            manifest = builder.build(ROOT / "behavior_cases", output, root / "artifacts")

            self.assertEqual(manifest["run_count"], 1)
            self.assertEqual(manifest["batch_count"], 1)
            self.assertIn("adapter_result.json", manifest["excluded_artifacts"])
            self.assertEqual(manifest["registration_count"], 1)
            self.assertIn("report_builder", manifest["entrypoints"])
            self.assertFalse((output / "runs" / "run-1" / "adapter_result.json").exists())
            self.assertFalse((output / "runs" / "run-1" / "final_response.txt").exists())
            self.assertTrue((output / "batches" / "batch-1" / "manifest.json").exists())
            public_registration = json.loads((output / "batches" / "batch-1" / "registration.json").read_text(encoding="utf-8"))
            self.assertEqual(public_registration["schema"], "evidence-bounded-debugging-public-registration-v1")
            self.assertNotIn("command", json.dumps(public_registration))
            self.assertNotIn("case_root", json.dumps(public_registration))
            self.assertNotIn("variant_id", json.dumps(public_registration))
            self.assertTrue((output / "README.md").exists())
            self.assertNotIn(str(root), (output / "README.md").read_text(encoding="utf-8"))
            public_annotations = json.loads((output / "runs" / "run-1" / "behavioral_annotations.json").read_text(encoding="utf-8"))
            self.assertNotIn("revealed_factors", public_annotations)
            self.assertFalse(public_annotations["repair_attempted"])
            self.assertEqual(public_annotations["edit_count"], 0)
            self.assertEqual(public_annotations["termination_reason"], "evidence collected")
            self.assertFalse(public_annotations["budget_exhausted"])
            public_trace = json.loads((output / "runs" / "run-1" / "event_trace.json").read_text(encoding="utf-8"))
            self.assertNotIn("reveals", public_trace["events"][0])
            public_run = json.loads((output / "runs" / "run-1" / "run.json").read_text(encoding="utf-8"))
            self.assertNotIn("declaration", public_run["verifier_result"])
            public_case = json.loads((output / "cases" / "dashboard-filter-refresh" / "family.json").read_text(encoding="utf-8"))
            self.assertNotIn("hidden_cause", public_case["variants"][0])
            self.assertNotIn("reveals", public_case["variants"][0]["observations"][0])


if __name__ == "__main__":
    unittest.main()
