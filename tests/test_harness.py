from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from cursor_eval.adapters import RealCursorAdapter, RealInvocationBlocked
from cursor_eval.artifacts import ArtifactExistsError, write_once
from cursor_eval.canonical import file_manifest, instruction_file_hashes, load_case, materialize_case
from cursor_eval.events import EventLog
from cursor_eval.observer import MutationObserver
from cursor_eval.registration import FROZEN_MODEL_IDS, build_registration, executor_binding, validate_registration
from cursor_eval.reservation import ReservationLedger


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class HarnessTests(unittest.TestCase):
    def test_canonical_materialization_is_clean_and_hides_runner_files(self):
        case = load_case(PROJECT_ROOT / "cases" / "recovery" / "canonical.json")
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            materialize_case(case, workspace)
            self.assertEqual(set(file_manifest(workspace)), set(case.files))
            self.assertEqual(instruction_file_hashes(workspace), {})
            self.assertFalse((workspace / "src/cursor_eval/verifiers.py").exists())
            self.assertFalse((workspace / "canonical.json").exists())

    def test_observer_records_revert_and_create_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tracked = root / "tracked.txt"
            tracked.write_text("before", encoding="utf-8")
            observer = MutationObserver(root, interval_seconds=0.01)
            observer.start()
            tracked.write_text("temporary", encoding="utf-8")
            time.sleep(0.05)
            tracked.write_text("before", encoding="utf-8")
            transient = root / "transient.txt"
            transient.write_text("created", encoding="utf-8")
            time.sleep(0.05)
            transient.unlink()
            time.sleep(0.05)
            summary = observer.stop()
            self.assertIn("tracked.txt", summary["reverted_paths"])
            self.assertIn("transient.txt", summary["created_then_deleted_paths"])
            self.assertGreaterEqual(len(summary["events"]), 4)

    def test_artifacts_are_write_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "artifact.txt"
            write_once(path, "one")
            with self.assertRaises(ArtifactExistsError):
                write_once(path, "two")
            self.assertEqual(path.read_text(encoding="utf-8"), "one")

    def test_reservation_ledger_is_append_only_and_consumed_once(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = ReservationLedger(Path(directory))
            reservation = ledger.reserve("reg", "case", "model", 1)
            with self.assertRaises(RuntimeError):
                ledger.reserve("reg", "case", "model", 1)
            consumed = ledger.consume(reservation["reservation_id"], status="behavioral", run_id="run")
            self.assertEqual(consumed["state"], "consumed")
            with self.assertRaises(RuntimeError):
                ledger.consume(reservation["reservation_id"], status="behavioral", run_id="run-2")
            records = [json.loads(line) for line in (Path(directory) / "reservations.jsonl").read_text().splitlines()]
            self.assertEqual(len(records), 2)

    def test_real_adapter_command_is_deterministic_and_blocked(self):
        adapter = RealCursorAdapter()
        command = adapter.command_for(Path("/tmp/eval-workspace"), "Fix the bug", FROZEN_MODEL_IDS[0])
        self.assertIn("--print", command)
        self.assertIn("--output-format", command)
        self.assertIn("stream-json", command)
        self.assertIn("--workspace", command)
        self.assertIn("--model", command)
        self.assertIn(FROZEN_MODEL_IDS[0], command)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RealInvocationBlocked):
                adapter.run(Path(directory), "Fix the bug", FROZEN_MODEL_IDS[0], EventLog())

    def test_registration_contains_frozen_matrix_and_binding(self):
        registration = build_registration(PROJECT_ROOT, registration_date="2026-08-16")
        self.assertEqual(registration["selected_models"], list(FROZEN_MODEL_IDS))
        self.assertEqual(len(registration["trial_matrix"]), 30)
        self.assertTrue(all(slot["state"] == "pending" for slot in registration["trial_matrix"]))
        self.assertEqual(registration["inventory_evidence"]["sha256"], "442066DD7CE7EC51C20C66EA4983EAB160631147B495C6E86098E7C0C8416DF5")
        self.assertEqual(registration["executor_critical_binding"], executor_binding(PROJECT_ROOT))

    def test_case_verifier_source_is_not_materialized(self):
        for case_id in ("recovery", "minimal_patch", "hidden_invariant"):
            case = load_case(PROJECT_ROOT / "cases" / case_id / "canonical.json")
            with tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory) / "workspace"
                materialize_case(case, workspace)
                self.assertFalse(any(path.name == "verifiers.py" for path in workspace.rglob("*")))


if __name__ == "__main__":
    unittest.main()
