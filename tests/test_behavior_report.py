from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from evidence_eval.behavior_report import BehaviorReportError, build_behavior_report


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _manifest(run_ids: list[tuple[str, int]]) -> dict[str, object]:
    planned = []
    results = []
    for run_id, variant_slot in run_ids:
        planned.append(
            {
                "adapter_id": "jsonl-provider-worker",
                "condition_id": "condition-a",
                "family_id": "dashboard-filter-refresh",
                "model_id": "model-a",
                "provider": "provider-a",
                "repetition": 1,
                "run_id": run_id,
                "variant_slot": variant_slot,
            }
        )
        results.append(
            {
                "condition_id": "condition-a",
                "execution_status": "completed",
                "family_id": "dashboard-filter-refresh",
                "infrastructure_censored": False,
                "repetition": 1,
                "run_id": run_id,
                "variant_slot": variant_slot,
                "verifier_passed": variant_slot == 1,
                "verifier_status": "passed" if variant_slot == 1 else "failed",
            }
        )
    return {
        "schema": "evidence-bounded-debugging-batch-v1",
        "batch_id": "batch-a",
        "conditions": [
            {
                "adapter_id": "jsonl-provider-worker",
                "condition_id": "condition-a",
                "model_id": "model-a",
                "network_required": False,
                "provider": "provider-a",
                "reasoning_effort": None,
            }
        ],
        "planned_trials": planned,
        "results": results,
    }


def _run(run_root: Path, run_id: str, variant_id: str, *, censored: bool = False, action: str = "search") -> None:
    _write_json(
        run_root / "run.json",
        {
            "run_id": run_id,
            "family_id": "dashboard-filter-refresh",
            "registration_id": "condition-a",
            "execution_status": "adapter_timeout" if censored else "completed",
            "infrastructure_censored": censored,
            "variant_id": variant_id,
            "condition": {
                "provider": "provider-a",
                "model_id": "model-a",
                "adapter_id": "jsonl-provider-worker",
                "prompt": "internal prompt",
            },
            "verifier_result": {
                "status": "infrastructure_censored" if censored else "failed",
                "passed": False,
                "declaration": {"hidden_cause": "secret answer key"},
            },
        },
    )
    if censored:
        return
    _write_json(
        run_root / "event_trace.json",
        {
            "variant_id": variant_id,
            "revealed_factors": ["hidden answer key"],
            "events": [
                {
                    "kind": "action",
                    "action": action,
                    "target": "dashboard",
                    "accepted": True,
                    "reveals": ["hidden answer key"],
                },
                {
                    "kind": "checkpoint",
                    "leading_hypothesis": "The query is not passed to the data request.",
                    "confidence": 0.8,
                },
                {"kind": "stop", "reason": "evidence collected"},
            ],
            "remaining_cost": 3,
        },
    )


class BehavioralReportTests(unittest.TestCase):
    def test_report_is_paired_and_public_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_one = "batch-a-condition-a-dashboard-filter-refresh-v1-r1"
            run_two = "batch-a-condition-a-dashboard-filter-refresh-v2-r1"
            batch = root / "batches" / "batch-a"
            _write_json(batch / "manifest.json", _manifest([(run_one, 1), (run_two, 2)]))
            _run(root / "runs" / run_two, run_two, "query-omitted", action="inspect")
            _run(root / "runs" / run_one, run_one, "cache-key-static")

            report = build_behavior_report(root, source_kind="internal_artifacts")

            self.assertEqual(report["source"]["run_count"], 2)
            self.assertEqual([run["run_id"] for run in report["runs"]], [run_one, run_two])
            self.assertEqual(len(report["comparisons"]), 1)
            comparison = report["comparisons"][0]
            self.assertEqual(comparison["first_variant_slot"], 1)
            self.assertEqual(comparison["second_variant_slot"], 2)
            self.assertTrue(comparison["behavior_changed"])
            self.assertTrue(comparison["comparison_is_causal_only_if_pre_registered"])
            self.assertEqual(report["runs"][0]["behavior"]["first_action"], "search")
            self.assertNotIn("variant_id", json.dumps(report))
            self.assertNotIn("hidden_cause", json.dumps(report))
            self.assertNotIn("adapter_result", json.dumps(report))
            self.assertNotIn("internal prompt", json.dumps(report))
            self.assertNotIn("hidden answer key", json.dumps(report))

    def test_censorship_is_separate_and_missing_trace_is_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_id = "batch-a-condition-a-dashboard-filter-refresh-v1-r1"
            _write_json(root / "batches" / "batch-a" / "manifest.json", _manifest([(run_id, 1)]))
            _run(root / "runs" / run_id, run_id, "query-omitted", censored=True)

            report = build_behavior_report(root, source_kind="internal_artifacts")

            entry = report["runs"][0]
            self.assertTrue(entry["infrastructure_censored"])
            self.assertEqual(entry["execution_status"], "adapter_timeout")
            self.assertEqual(entry["verifier_status"], "infrastructure_censored")
            self.assertFalse(entry["behavior"]["action_sequence"])
            self.assertIsNone(entry["behavior"]["repair_attempted"])

    def test_public_release_input_and_annotation_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_id = "public-condition-dashboard-filter-refresh-v1-r1"
            _write_json(root / "batches" / "public-batch" / "manifest.json", _manifest([(run_id, 1)]))
            run_root = root / "runs" / run_id
            _write_json(
                run_root / "run.json",
                {
                    "run_id": run_id,
                    "family_id": "dashboard-filter-refresh",
                    "registration_id": "condition-a",
                    "execution_status": "completed",
                    "infrastructure_censored": False,
                    "variant_id": "redacted",
                    "verifier_result": {"status": "failed"},
                },
            )
            _write_json(
                run_root / "behavioral_annotations.json",
                {
                    "variant_id": "redacted",
                    "action_sequence": ["inspect"],
                    "first_action": "inspect",
                    "repair_attempted": False,
                    "edit_count": 0,
                    "revealed_factors": ["removed"],
                    "unknown_field": "ignored",
                },
            )

            report = build_behavior_report(root, source_kind="public_release")

            self.assertEqual(report["source"]["source_kind"], "public_release")
            self.assertEqual(report["runs"][0]["behavior"]["action_sequence"], ["inspect"])
            self.assertFalse(report["runs"][0]["behavior"]["repair_attempted"])
            self.assertNotIn("unknown_field", json.dumps(report))
            self.assertNotIn("revealed_factors", json.dumps(report))

    def test_malformed_optional_artifact_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_id = "batch-a-condition-a-dashboard-filter-refresh-v1-r1"
            _write_json(root / "batches" / "batch-a" / "manifest.json", _manifest([(run_id, 1)]))
            _run(root / "runs" / run_id, run_id, "query-omitted")
            (root / "runs" / run_id / "event_trace.json").write_text("not json", encoding="utf-8")

            with self.assertRaises(BehaviorReportError):
                build_behavior_report(root, source_kind="internal_artifacts")

    def test_duplicate_run_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_id = "batch-a-condition-a-dashboard-filter-refresh-v1-r1"
            _write_json(root / "batches" / "batch-a" / "manifest.json", _manifest([(run_id, 1)]))
            _run(root / "runs" / "one", run_id, "query-omitted")
            _run(root / "runs" / "two", run_id, "query-omitted")

            with self.assertRaises(BehaviorReportError):
                build_behavior_report(root, source_kind="internal_artifacts")

    def test_malformed_batch_metadata_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_json(
                root / "batches" / "batch-a" / "manifest.json",
                {"schema": "evidence-bounded-debugging-batch-v1", "batch_id": "batch-a", "conditions": "not-a-list"},
            )
            (root / "runs").mkdir(parents=True)

            with self.assertRaises(BehaviorReportError):
                build_behavior_report(root, source_kind="internal_artifacts")


if __name__ == "__main__":
    unittest.main()
