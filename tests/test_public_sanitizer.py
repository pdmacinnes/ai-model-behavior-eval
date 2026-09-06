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
            "events": [{"kind": "action", "reveals": ["cache key behavior"], "content": "evidence"}],
        }
        sanitized = sanitize_public_trace(trace)
        self.assertEqual(sanitized["variant_id"], "redacted")
        self.assertNotIn("reveals", sanitized["events"][0])

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

    def test_run_sanitizer_removes_verifier_declaration(self):
        run = {
            "variant_id": "query-omitted",
            "verifier_result": {"status": "declarative_only", "declaration": {"expected_cause": "query propagation"}},
        }
        sanitized = sanitize_public_run(run)
        self.assertEqual(sanitized["variant_id"], "redacted")
        self.assertEqual(sanitized["verifier_result"], {"status": "declarative_only"})

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
        variant = sanitized["variants"][0]
        self.assertEqual(variant["variant_id"], "variant-1")
        self.assertNotIn("hidden_cause", variant)
        self.assertNotIn("verifier", variant)
        self.assertNotIn("calibration", variant)
        self.assertNotIn("reveals", variant["observations"][0])
        self.assertEqual(sanitized["perturbations"], [{"type": "counterfactual"}])


if __name__ == "__main__":
    unittest.main()
