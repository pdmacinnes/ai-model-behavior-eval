from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from cursor_eval.artifacts import ArtifactExistsError

from evidence_eval.pilot import (
    PILOT_REGISTRATION_SCHEMA,
    PilotCondition,
    PilotRegistration,
    PilotRegistrationError,
    load_pilot_registration,
    plan_pilot_trials,
    run_pilot_batch,
)
from evidence_eval.schema import load_case_family


ROOT = Path(__file__).resolve().parents[1]
REFERENCE_WORKER = ROOT / "scripts" / "reference_workspace_worker.py"


def _reference_registration(output_root: Path, *, batch_id: str = "reference-test", repetitions: int = 1) -> PilotRegistration:
    return PilotRegistration(
        batch_id=batch_id,
        harness_version="0.1.0",
        case_root=ROOT / "behavior_cases",
        family_ids=("dashboard-filter-refresh", "session-refresh-role", "pagination-offset"),
        variant_ids={},
        repetitions=repetitions,
        trial_timeout_seconds=10.0,
        artifacts_root=output_root,
        workspace_parent=output_root / "workspaces",
        conditions=(
            PilotCondition(
                condition_id="reference-worker",
                provider="deterministic",
                model_id="reference-worker",
                adapter_id="jsonl-reference-worker",
                command=(sys.executable, str(REFERENCE_WORKER)),
                reasoning_effort=None,
                network_required=False,
                timeout_seconds=5.0,
            ),
        ),
    )


class PilotBatchTests(unittest.TestCase):
    def test_registration_rejects_unknown_fields_and_requires_policy_for_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = {
                "schema": PILOT_REGISTRATION_SCHEMA,
                "batch_id": "registration-test",
                "harness_version": "0.1.0",
                "case_root": str(ROOT / "behavior_cases"),
                "family_ids": ["dashboard-filter-refresh"],
                "repetitions": 1,
                "trial_timeout_seconds": 10,
                "artifacts_root": str(root / "artifacts"),
                "workspace_parent": str(root / "workspaces"),
                "conditions": [
                    {
                        "condition_id": "reference",
                        "provider": "deterministic",
                        "model_id": "reference",
                        "adapter_id": "reference",
                        "command": [sys.executable, str(REFERENCE_WORKER)],
                        "reasoning_effort": None,
                        "network_required": False,
                        "timeout_seconds": 5,
                    }
                ],
            }
            path = root / "registration.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            payload["cwd"] = "."
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(PilotRegistrationError, "unknown fields"):
                load_pilot_registration(path)

            del payload["cwd"]
            payload["conditions"][0]["network_required"] = True
            path.write_text(json.dumps(payload), encoding="utf-8")
            registration = load_pilot_registration(path)
            with self.assertRaisesRegex(PilotRegistrationError, "allow-network"):
                run_pilot_batch(registration)

            payload["conditions"][0]["network_required"] = False
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(PilotRegistrationError, "only valid"):
                run_pilot_batch(load_pilot_registration(path), allow_network=True)

    def test_planned_ids_use_variant_slots_not_answer_key_ids(self):
        family = load_case_family(ROOT / "behavior_cases" / "dashboard-filter-refresh" / "family.json")
        registration = replace(
            _reference_registration(Path("results") / "pilot-test", repetitions=2),
            family_ids=(family.family_id,),
        )
        planned = plan_pilot_trials(registration, {family.family_id: family})
        self.assertEqual(len(planned), 4)
        self.assertTrue(all("-v1-" in trial.run_id or "-v2-" in trial.run_id for trial in planned))
        self.assertTrue(all("cache-key" not in trial.run_id for trial in planned))
        self.assertEqual({trial.variant_slot for trial in planned}, {1, 2})

    def test_reference_worker_completes_full_smoke_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = run_pilot_batch(_reference_registration(Path(directory) / "artifacts"))
            self.assertEqual(len(manifest["planned_trials"]), 6)
            self.assertEqual(len(manifest["results"]), 6)
            self.assertTrue(all(item["execution_status"] == "completed" for item in manifest["results"]))
            self.assertTrue(all(not item["infrastructure_censored"] for item in manifest["results"]))
            serialized = json.dumps(manifest)
            self.assertNotIn("command", serialized)
            self.assertNotIn("variant_id", serialized)
            self.assertTrue((Path(directory) / "artifacts" / "batches" / "reference-test" / "manifest.json").exists())

    def test_batch_manifest_records_safe_provenance_and_budget_override(self):
        with tempfile.TemporaryDirectory() as directory:
            registration = replace(
                _reference_registration(Path(directory) / "artifacts", batch_id="provenance-test"),
                family_ids=("dashboard-filter-refresh",),
                budget_overrides={"dashboard-filter-refresh": 14},
            )
            manifest = run_pilot_batch(registration)
            self.assertRegex(manifest["source_revision"], r"^(?:[0-9a-f]{40}|unavailable)$")
            self.assertEqual(manifest["budget_overrides"], {"dashboard-filter-refresh": 14})
            self.assertEqual(manifest["registration_summary"]["repetitions"], 1)
            self.assertNotIn("command", json.dumps(manifest))

    def test_batch_continues_after_worker_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            registration = _reference_registration(Path(directory) / "artifacts", batch_id="failure-test")
            failing = PilotCondition(
                condition_id="failing-worker",
                provider="deterministic",
                model_id="failing-worker",
                adapter_id="failing-worker",
                command=(sys.executable, "-c", "raise SystemExit(1)"),
                reasoning_effort=None,
                network_required=False,
                timeout_seconds=5.0,
            )
            registration = replace(registration, conditions=(failing,))
            manifest = run_pilot_batch(registration)
            self.assertEqual(len(manifest["results"]), 6)
            self.assertTrue(all(item["execution_status"] == "adapter_error" for item in manifest["results"]))
            self.assertTrue(all(item["infrastructure_censored"] for item in manifest["results"]))

    def test_batch_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            registration = _reference_registration(Path(directory) / "artifacts", batch_id="no-overwrite-test")
            run_pilot_batch(registration)
            with self.assertRaises(ArtifactExistsError):
                run_pilot_batch(registration)


if __name__ == "__main__":
    unittest.main()
