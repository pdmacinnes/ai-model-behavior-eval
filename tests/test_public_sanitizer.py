from __future__ import annotations

import unittest

from evidence_eval.public import (
    sanitize_public_artifact,
    sanitize_public_case_family,
    sanitize_public_run,
    sanitize_public_trace,
    validate_public_batch_manifest,
)


class PublicSanitizerTests(unittest.TestCase):
    def test_trace_sanitizer_removes_answer_key_annotations(self):
        trace = {
            "variant_id": "cache-key-static",
            "events": [{"kind": "action", "reveals": ["cache key behavior"], "content": "workspace source"}],
        }
        sanitized = sanitize_public_trace(trace)
        self.assertNotIn("variant_id", sanitized)
        self.assertNotIn("reveals", sanitized["events"][0])
        self.assertNotIn("content", sanitized["events"][0])
        self.assertEqual(sanitized["events"][0]["content_chars"], len("workspace source"))

    def test_annotations_artifact_sanitizer_removes_top_level_answer_keys(self):
        annotations = {"revealed_factors": ["query propagation"], "first_action": "trace"}
        sanitized = sanitize_public_artifact("behavioral_annotations.json", annotations)
        self.assertNotIn("revealed_factors", sanitized)
        self.assertEqual(sanitized["first_action"], "trace")

    def test_raw_adapter_artifacts_are_not_publishable(self):
        with self.assertRaisesRegex(ValueError, "not publishable"):
            sanitize_public_artifact("adapter_result.json", {"final_response": "provider output"})

    def test_batch_manifest_gate_rejects_internal_fields(self):
        with self.assertRaisesRegex(ValueError, "forbidden field"):
            validate_public_batch_manifest({"schema": "evidence-bounded-debugging-batch-v1", "command": ["worker"]})

    def test_batch_manifest_gate_rejects_variant_slots_and_raw_run_ids(self):
        with self.assertRaisesRegex(ValueError, "forbidden field"):
            validate_public_batch_manifest({"planned_trials": [{"variant_slot": 1}]})
        with self.assertRaisesRegex(ValueError, "non-opaque run id"):
            validate_public_batch_manifest({"planned_trials": [{"run_id": "internal-v1-r1"}]})

    def test_run_sanitizer_removes_verifier_declaration(self):
        run = {
            "variant_id": "query-omitted",
            "verifier_result": {
                "status": "declarative_only",
                "passed": False,
                "declaration": {"expected_cause": "query propagation"},
            },
        }
        sanitized = sanitize_public_run(run)
        self.assertNotIn("variant_id", sanitized)
        self.assertEqual(sanitized["verifier_result"], {"status": "declarative_only", "passed": False})

    def test_verifier_artifact_keeps_only_status_and_passed(self):
        sanitized = sanitize_public_artifact(
            "verifier_result.json",
            {
                "verifier_id": "dashboard-filter-refresh:query-omitted-v1",
                "status": "failed",
                "passed": False,
                "checks": {"page_passes_selected_range": False},
                "regressions": ["query omitted"],
            },
        )
        self.assertEqual(sanitized, {"status": "failed", "passed": False})

    def test_case_sanitizer_removes_answer_key_fields(self):
        case = {
            "family_id": "example",
            "perturbations": [{"type": "counterfactual", "description": "hidden cause"}],
            "variants": [{
                "variant_id": "query-omitted",
                "hidden_cause": "query propagation",
                "verifier": {"expected_cause": "query propagation"},
                "calibration": {"mutation_proof": {}},
                "observations": [{"content": "evidence", "reveals": ["query propagation"]}],
            }],
        }
        sanitized = sanitize_public_case_family(case)
        self.assertEqual(sanitized["variant_count"], 1)
        self.assertNotIn("variants", sanitized)
        self.assertNotIn("files", sanitized)
        self.assertNotIn("hypotheses", sanitized)
        self.assertNotIn("observations", sanitized)
        self.assertEqual(sanitized["perturbations"], [{"type": "counterfactual"}])


if __name__ == "__main__":
    unittest.main()
