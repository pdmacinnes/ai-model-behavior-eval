from __future__ import annotations

import unittest

from evidence_eval.public import sanitize_public_run, sanitize_public_trace


class PublicSanitizerTests(unittest.TestCase):
    def test_trace_sanitizer_removes_answer_key_annotations(self):
        trace = {
            "variant_id": "cache-key-static",
            "events": [{"kind": "action", "reveals": ["cache key behavior"], "content": "evidence"}],
        }
        sanitized = sanitize_public_trace(trace)
        self.assertEqual(sanitized["variant_id"], "redacted")
        self.assertNotIn("reveals", sanitized["events"][0])

    def test_run_sanitizer_removes_verifier_declaration(self):
        run = {
            "variant_id": "query-omitted",
            "verifier_result": {"status": "declarative_only", "declaration": {"expected_cause": "query propagation"}},
        }
        sanitized = sanitize_public_run(run)
        self.assertEqual(sanitized["variant_id"], "redacted")
        self.assertEqual(sanitized["verifier_result"], {"status": "declarative_only"})


if __name__ == "__main__":
    unittest.main()
