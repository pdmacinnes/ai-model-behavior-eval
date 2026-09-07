from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from evidence_eval.model_matrix import (
    FULL_FAMILY_IDS,
    ModelMatrixError,
    build_registration_payload,
    load_model_matrix,
    write_provider_registrations,
)
from evidence_eval.execution_policy import PROVIDER_CREDENTIAL_ENV, validate_execution_authorization
from evidence_eval.pilot import load_pilot_registration


ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = ROOT / "configs" / "model_matrix.json"


class ModelMatrixTests(unittest.TestCase):
    def test_catalog_contains_active_models_and_pending_meta(self):
        matrix = load_model_matrix(MATRIX_PATH)
        self.assertEqual(len(matrix.active_conditions), 11)
        self.assertEqual(
            {condition.model_id for condition in matrix.active_conditions},
            {
                "gpt-6-astra",
                "gpt-5.6-sol",
                "gpt-5.6-luna",
                "claude-fable-5-1",
                "claude-opus-5",
                "claude-sonnet-5",
                "gemini-3.8-flash",
                "grok-4.6",
                "deepseek-v4-pro",
                "qwen3.8-max-0902",
                "kimi-k2.6",
            },
        )
        self.assertEqual([item.provider for item in matrix.pending_conditions], ["meta"])
        self.assertEqual(matrix.providers, ("alibaba", "anthropic", "deepseek", "google", "moonshot", "openai", "xai"))
        google = matrix.conditions_for_provider("google")
        self.assertEqual(len(google), 1)
        self.assertEqual(google[0].transport, "google-gemini")

    def test_catalog_rejects_unknown_fields_and_placeholders(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "matrix.json"
            payload = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
            payload["active_conditions"][0]["api_key"] = "secret"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ModelMatrixError, "unknown fields"):
                load_model_matrix(path)

            payload = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
            payload["active_conditions"][0]["model_id"] = "pending"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ModelMatrixError, "placeholder"):
                load_model_matrix(path)

    def test_generated_registrations_have_expected_grouping_and_counts(self):
        matrix = load_model_matrix(MATRIX_PATH)
        smoke_trials = 0
        full_trials = 0
        for provider in matrix.providers:
            conditions = matrix.conditions_for_provider(provider)
            smoke = build_registration_payload(conditions, provider=provider, mode="smoke", project_root=ROOT)
            full = build_registration_payload(conditions, provider=provider, mode="full", project_root=ROOT)
            self.assertEqual(smoke["family_ids"], ["dashboard-filter-refresh"])
            self.assertEqual(smoke["repetitions"], 1)
            self.assertEqual(full["family_ids"], list(FULL_FAMILY_IDS))
            self.assertEqual(full["repetitions"], 2)
            for payload in (smoke, full):
                self.assertTrue(all(item["network_required"] for item in payload["conditions"]))
                self.assertTrue(all(item["adapter_id"] == "jsonl-provider-worker" for item in payload["conditions"]))
                self.assertTrue(all("--max-rounds" in item["command"] for item in payload["conditions"]))
                self.assertTrue(all("--max-conversation-messages" in item["command"] for item in payload["conditions"]))
                self.assertTrue(all("--max-conversation-chars" in item["command"] for item in payload["conditions"]))
                serialized = json.dumps(payload)
                self.assertNotIn("api_key", serialized.lower())
                self.assertNotIn("secret", serialized.lower())
                self.assertNotIn("verifier", serialized.lower())
            smoke_trials += len(conditions) * 2 * smoke["repetitions"]
            full_trials += len(conditions) * 6 * full["repetitions"]
        self.assertEqual(smoke_trials, 22)
        self.assertEqual(full_trials, 132)

    def test_batch_label_creates_distinguishable_rerun(self):
        matrix = load_model_matrix(MATRIX_PATH)
        payload = build_registration_payload(
            matrix.conditions_for_provider("openai"),
            provider="openai",
            mode="smoke",
            project_root=ROOT,
            batch_label="bounds-v2",
        )
        self.assertEqual(payload["batch_id"], "model-matrix-openai-smoke-bounds-v2")
        with self.assertRaisesRegex(ModelMatrixError, "safe identifier"):
            build_registration_payload(
                matrix.conditions_for_provider("openai"),
                provider="openai",
                mode="smoke",
                project_root=ROOT,
                batch_label="bounds/v2",
            )

    def test_generated_registrations_load_through_existing_parser(self):
        matrix = load_model_matrix(MATRIX_PATH)
        with tempfile.TemporaryDirectory() as directory:
            paths = write_provider_registrations(
                matrix,
                Path(directory),
                project_root=ROOT,
            )
            self.assertEqual(len(paths), 14)
            for path in paths:
                registration = load_pilot_registration(path)
                self.assertTrue(registration.conditions)
                self.assertTrue(all(condition.network_required for condition in registration.conditions))
                validate_execution_authorization(
                    registration,
                    allow_network=True,
                    environment={PROVIDER_CREDENTIAL_ENV: "test-only-placeholder"},
                )

    def test_generation_refuses_overwrite(self):
        matrix = load_model_matrix(MATRIX_PATH)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            write_provider_registrations(matrix, output, project_root=ROOT)
            with self.assertRaisesRegex(ModelMatrixError, "overwrite"):
                write_provider_registrations(matrix, output, project_root=ROOT)


if __name__ == "__main__":
    unittest.main()
