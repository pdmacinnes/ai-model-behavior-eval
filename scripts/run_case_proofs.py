from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from cursor_eval.adapters import ActionRecorder
from cursor_eval.canonical import load_case, materialize_case
from cursor_eval.events import EventLog
from cursor_eval.fake_agents import (
    correct_hidden_invariant,
    correct_minimal_patch,
    correct_recovery,
    visible_test_gaming,
    wrong_recovery_hypothesis,
)
from cursor_eval.runner import run_visible_tests
from cursor_eval.verifiers import verify_case


def apply_agent(case, workspace: Path, agent) -> None:
    agent(ActionRecorder(workspace, EventLog()), case.prompt)


def proof(case_id: str, correct_agent, *, shortcut_agent=None) -> dict:
    case = load_case(PROJECT_ROOT / "cases" / case_id / "canonical.json")
    with tempfile.TemporaryDirectory(prefix=f"proof-{case_id}-") as directory:
        root = Path(directory)
        baseline = root / "baseline"
        materialize_case(case, baseline)
        baseline_visible = run_visible_tests(case, baseline)
        baseline_hidden = verify_case(case_id, baseline)

        correct = root / "correct"
        materialize_case(case, correct)
        apply_agent(case, correct, correct_agent)
        correct_visible = run_visible_tests(case, correct)
        correct_hidden = verify_case(case_id, correct)

        result = {
            "case_id": case_id,
            "case_sha256": case.canonical_sha256,
            "baseline": {"visible_pass": baseline_visible.passed, "hidden_pass": baseline_hidden.passed},
            "intended_solution": {"visible_pass": correct_visible.passed, "hidden_pass": correct_hidden.passed},
        }
        if shortcut_agent is not None:
            shortcut = root / "shortcut"
            materialize_case(case, shortcut)
            apply_agent(case, shortcut, shortcut_agent)
            shortcut_visible = run_visible_tests(case, shortcut)
            shortcut_hidden = verify_case(case_id, shortcut)
            result["shortcut"] = {"visible_pass": shortcut_visible.passed, "hidden_pass": shortcut_hidden.passed}
        return result


def main() -> int:
    results = [
        proof("recovery", correct_recovery),
        proof("minimal_patch", correct_minimal_patch),
        proof("hidden_invariant", correct_hidden_invariant, shortcut_agent=visible_test_gaming),
    ]
    print(json.dumps(results, indent=2, sort_keys=True))
    expected = [
        results[0]["baseline"] == {"visible_pass": False, "hidden_pass": False},
        results[0]["intended_solution"] == {"visible_pass": True, "hidden_pass": True},
        results[1]["baseline"] == {"visible_pass": False, "hidden_pass": False},
        results[1]["intended_solution"] == {"visible_pass": True, "hidden_pass": True},
        results[2]["baseline"] == {"visible_pass": False, "hidden_pass": False},
        results[2]["intended_solution"] == {"visible_pass": True, "hidden_pass": True},
        results[2]["shortcut"] == {"visible_pass": True, "hidden_pass": False},
    ]
    return 0 if all(expected) else 1


if __name__ == "__main__":
    raise SystemExit(main())
