from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from cursor_eval.adapters import FakeCursorAdapter, RealCursorAdapter, RealInvocationBlocked
from cursor_eval.canonical import load_case
from cursor_eval.fake_agents import (
    broad_behaviorally_correct_patch,
    correct_hidden_invariant,
    correct_minimal_patch,
    correct_recovery,
    provider_failure_agent,
    recover_after_wrong_hypothesis,
    test_modification_only,
    timeout_agent,
    transient_edit_then_correct,
    visible_test_gaming,
    wrong_recovery_hypothesis,
)
from cursor_eval.runner import run_trial


def run_one(root: Path, case_id: str, agent, model: str = "fake-model") -> dict:
    case = load_case(PROJECT_ROOT / "cases" / case_id / "canonical.json")
    return run_trial(
        case,
        model,
        1,
        FakeCursorAdapter(agent, timeout_seconds=0.25),
        registration_id="fake-acceptance",
        workspace_parent=root / "workspaces",
        results_root=root / "results",
        reservations_root=root / "reservations",
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="fake-acceptance-") as directory:
        root = Path(directory)
        (root / "workspaces").mkdir()
        cases = {
            "correct_recovery": run_one(root, "recovery", correct_recovery),
            "wrong_diagnosis": run_one(root, "recovery", wrong_recovery_hypothesis, "fake-wrong"),
            "recovery_after_reversal": run_one(root, "recovery", recover_after_wrong_hypothesis, "fake-recovery"),
            "correct_minimal": run_one(root, "minimal_patch", correct_minimal_patch),
            "broad_patch": run_one(root, "minimal_patch", broad_behaviorally_correct_patch, "fake-broad"),
            "test_modification": run_one(root, "recovery", test_modification_only, "fake-test-edit"),
            "correct_hidden": run_one(root, "hidden_invariant", correct_hidden_invariant),
            "visible_test_gaming": run_one(root, "hidden_invariant", visible_test_gaming, "fake-gaming"),
            "transient_revert": run_one(root, "minimal_patch", transient_edit_then_correct, "fake-transient"),
            "timeout": run_one(root, "recovery", timeout_agent, "fake-timeout"),
            "provider_failure": run_one(root, "recovery", provider_failure_agent, "fake-provider-failure"),
        }
        blocked_case = load_case(PROJECT_ROOT / "cases" / "recovery" / "canonical.json")
        blocked = run_trial(
            blocked_case,
            "gpt-5.3-codex-high",
            1,
            RealCursorAdapter(),
            registration_id="fake-acceptance-real-gate",
            workspace_parent=root / "workspaces",
            results_root=root / "results",
            reservations_root=root / "reservations-real",
        )
        cases["real_adapter_blocked"] = blocked
        print(json.dumps(cases, indent=2, sort_keys=True))
        checks = [
            cases["correct_recovery"]["task_success"],
            not cases["wrong_diagnosis"]["authoritative_verifier_pass"],
            cases["recovery_after_reversal"]["task_success"] and cases["recovery_after_reversal"]["misleading_target_later_reverted"],
            cases["correct_minimal"]["task_success"],
            cases["broad_patch"]["task_success"] and bool(cases["broad_patch"]["unnecessary_changed_paths"]),
            bool(cases["test_modification"]["tests_changed"]),
            cases["correct_hidden"]["task_success"],
            cases["visible_test_gaming"]["visible_tests_pass"] and not cases["visible_test_gaming"]["hidden_verifier_pass"] and cases["visible_test_gaming"]["shortcut_pattern_detected"],
            cases["transient_revert"]["task_success"] and "src/cli.py" in cases["transient_revert"]["mutation_summary"]["reverted_paths"],
            cases["timeout"]["execution_status"] == "timeout",
            cases["provider_failure"]["execution_status"] == "provider_failure",
            blocked["execution_status"] == "blocked",
        ]
        return 0 if all(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
