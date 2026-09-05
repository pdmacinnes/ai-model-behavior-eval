from __future__ import annotations

import unittest
from pathlib import Path

from evidence_eval.analysis import analyze_trace, compare_variants
from evidence_eval.calibration import calibrate_case_family
from evidence_eval.case_validation import validate_case_family
from evidence_eval.protocol import EvidenceSession
from evidence_eval.schema import load_case_family


ROOT = Path(__file__).resolve().parents[1]


class BehaviorProtocolTests(unittest.TestCase):
    def test_all_behavior_case_families_validate(self):
        paths = sorted((ROOT / "behavior_cases").glob("*/family.json"))
        self.assertGreaterEqual(len(paths), 3)
        for path in paths:
            report = validate_case_family(load_case_family(path))
            self.assertTrue(report["valid"], report)

    def test_all_behavior_case_families_pass_deterministic_calibration(self):
        paths = sorted((ROOT / "behavior_cases").glob("*/family.json"))
        for path in paths:
            report = calibrate_case_family(load_case_family(path))
            self.assertTrue(report["valid"], report)

    def test_budget_and_unsupported_actions_are_recorded(self):
        family = load_case_family(ROOT / "behavior_cases" / "dashboard-filter-refresh" / "family.json")
        session = EvidenceSession(family, family.variants[0])
        rejected = session.request("not-a-tool", "anything")
        self.assertFalse(rejected.accepted)
        accepted = session.request("trace", "metrics-request")
        self.assertTrue(accepted.accepted)
        self.assertGreaterEqual(accepted.remaining_cost, 0)
        self.assertEqual(session.to_record()["events"][0]["kind"], "rejected_action")

    def test_variant_analysis_reports_behavioral_change(self):
        family = load_case_family(ROOT / "behavior_cases" / "dashboard-filter-refresh" / "family.json")
        observations = []
        for variant in family.variants:
            session = EvidenceSession(family, variant)
            session.request("trace", "metrics-request")
            session.checkpoint(
                leading_hypothesis=variant.hidden_cause,
                alternative_hypothesis="other plausible cause",
                confidence=0.7,
                changed_by="trace result",
                next_action="stop",
            )
            session.stop("diagnosis localized")
            observations.append(analyze_trace(session.to_record()))
        comparison = compare_variants(observations[0], observations[1])
        self.assertTrue(comparison["behavior_changed"])
        self.assertIn("revealed_factors", comparison["changed_fields"])

    def test_checkpoint_rejects_invalid_confidence(self):
        family = load_case_family(ROOT / "behavior_cases" / "dashboard-filter-refresh" / "family.json")
        session = EvidenceSession(family, family.variants[0])
        with self.assertRaises(ValueError):
            session.checkpoint(
                leading_hypothesis="a",
                alternative_hypothesis="b",
                confidence=1.1,
                changed_by="test",
                next_action="stop",
            )


if __name__ == "__main__":
    unittest.main()
