from __future__ import annotations

import unittest
from pathlib import Path

from cursor_eval.canonical import load_case, materialize_case
from cursor_eval.fake_agents import correct_hidden_invariant, correct_minimal_patch, correct_recovery, visible_test_gaming
from cursor_eval.adapters import ActionRecorder
from cursor_eval.events import EventLog
from cursor_eval.runner import run_visible_tests
from cursor_eval.verifiers import verify_case
import tempfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class CaseProofTests(unittest.TestCase):
    def _proof(self, case_id, correct_agent, shortcut_agent=None):
        case = load_case(PROJECT_ROOT / "cases" / case_id / "canonical.json")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = root / "baseline"
            materialize_case(case, baseline)
            self.assertFalse(run_visible_tests(case, baseline).passed)
            self.assertFalse(verify_case(case_id, baseline).passed)
            correct = root / "correct"
            materialize_case(case, correct)
            correct_agent(ActionRecorder(correct, EventLog()), case.prompt)
            self.assertTrue(run_visible_tests(case, correct).passed)
            self.assertTrue(verify_case(case_id, correct).passed)
            if shortcut_agent:
                shortcut = root / "shortcut"
                materialize_case(case, shortcut)
                shortcut_agent(ActionRecorder(shortcut, EventLog()), case.prompt)
                self.assertTrue(run_visible_tests(case, shortcut).passed)
                self.assertFalse(verify_case(case_id, shortcut).passed)

    def test_recovery_case(self):
        self._proof("recovery", correct_recovery)

    def test_minimal_patch_case(self):
        self._proof("minimal_patch", correct_minimal_patch)

    def test_hidden_invariant_case(self):
        self._proof("hidden_invariant", correct_hidden_invariant, visible_test_gaming)


if __name__ == "__main__":
    unittest.main()
