from __future__ import annotations

import sys
import unittest
from pathlib import Path

from evidence_eval.execution_policy import (
    PROVIDER_CREDENTIAL_ENV,
    ExecutionPolicyError,
    live_environment_names,
    validate_execution_authorization,
)
from evidence_eval.pilot import PilotCondition, PilotRegistration


ROOT = Path(__file__).resolve().parents[1]
APPROVED_WORKER = ROOT / "scripts" / "openai_compatible_workspace_worker.py"


def _registration(*conditions: PilotCondition) -> PilotRegistration:
    return PilotRegistration(
        batch_id="policy-test",
        harness_version="0.1.0",
        case_root=ROOT / "behavior_cases",
        family_ids=("dashboard-filter-refresh",),
        variant_ids={},
        repetitions=1,
        trial_timeout_seconds=10.0,
        artifacts_root=ROOT / "results" / "policy-test",
        workspace_parent=ROOT / "results" / "policy-test" / "workspaces",
        conditions=conditions,
    )


def _live_condition(**overrides: object) -> PilotCondition:
    values: dict[str, object] = {
        "condition_id": "live",
        "provider": "provider",
        "model_id": "model",
        "adapter_id": "jsonl-provider-worker",
        "command": (sys.executable, str(APPROVED_WORKER), "--transport", "openai-compatible"),
        "reasoning_effort": None,
        "network_required": True,
        "timeout_seconds": 5.0,
    }
    values.update(overrides)
    return PilotCondition(**values)


class ExecutionPolicyTests(unittest.TestCase):
    def test_network_requires_explicit_batch_authorization(self):
        with self.assertRaisesRegex(ExecutionPolicyError, "allow-network"):
            validate_execution_authorization(
                _registration(_live_condition()),
                allow_network=False,
                environment={PROVIDER_CREDENTIAL_ENV: "secret"},
            )

    def test_non_network_batch_rejects_network_flag(self):
        condition = _live_condition(network_required=False, adapter_id="jsonl-reference-worker")
        with self.assertRaisesRegex(ExecutionPolicyError, "only valid"):
            validate_execution_authorization(
                _registration(condition),
                allow_network=True,
                environment={},
            )

    def test_approved_worker_requires_allowlisted_credential(self):
        validate_execution_authorization(
            _registration(_live_condition()),
            allow_network=True,
            environment={PROVIDER_CREDENTIAL_ENV: "secret"},
        )
        with self.assertRaisesRegex(ExecutionPolicyError, PROVIDER_CREDENTIAL_ENV):
            validate_execution_authorization(
                _registration(_live_condition()),
                allow_network=True,
                environment={},
            )

    def test_responses_transport_is_allowlisted_for_live_batches(self):
        condition = _live_condition(
            command=(sys.executable, str(APPROVED_WORKER), "--transport", "openai-responses"),
        )
        validate_execution_authorization(
            _registration(condition),
            allow_network=True,
            environment={PROVIDER_CREDENTIAL_ENV: "secret"},
        )

    def test_gemini_transport_is_allowlisted_for_live_batches(self):
        condition = _live_condition(
            command=(sys.executable, str(APPROVED_WORKER), "--transport", "google-gemini"),
        )
        validate_execution_authorization(
            _registration(condition),
            allow_network=True,
            environment={PROVIDER_CREDENTIAL_ENV: "secret"},
        )

    def test_conversation_bound_arguments_are_allowlisted(self):
        condition = _live_condition(
            command=(
                sys.executable,
                str(APPROVED_WORKER),
                "--transport",
                "openai-responses",
                "--max-rounds",
                "24",
                "--max-conversation-messages",
                "48",
                "--max-conversation-chars",
                "192000",
                "--request-timeout-seconds",
                "120.0",
            ),
        )
        validate_execution_authorization(
            _registration(condition),
            allow_network=True,
            environment={PROVIDER_CREDENTIAL_ENV: "secret"},
        )

    def test_responses_transport_requires_network_declaration(self):
        condition = _live_condition(
            command=(sys.executable, str(APPROVED_WORKER), "--transport", "openai-responses"),
            network_required=False,
        )
        with self.assertRaisesRegex(ExecutionPolicyError, "network_required"):
            validate_execution_authorization(
                _registration(condition),
                allow_network=False,
                environment={},
            )

    def test_gemini_transport_requires_network_declaration(self):
        condition = _live_condition(
            command=(sys.executable, str(APPROVED_WORKER), "--transport", "google-gemini"),
            network_required=False,
        )
        with self.assertRaisesRegex(ExecutionPolicyError, "network_required"):
            validate_execution_authorization(
                _registration(condition),
                allow_network=False,
                environment={},
            )

    def test_unapproved_worker_identity_and_arguments_fail_closed(self):
        with self.assertRaisesRegex(ExecutionPolicyError, "adapter identifier"):
            validate_execution_authorization(
                _registration(_live_condition(adapter_id="other-worker")),
                allow_network=True,
                environment={PROVIDER_CREDENTIAL_ENV: "secret"},
            )
        with self.assertRaisesRegex(ExecutionPolicyError, "unapproved argument"):
            validate_execution_authorization(
                _registration(_live_condition(command=(*_live_condition().command, "--api-key-env", "OTHER"))),
                allow_network=True,
                environment={PROVIDER_CREDENTIAL_ENV: "secret"},
            )
        with self.assertRaisesRegex(ExecutionPolicyError, "positive numbers"):
            validate_execution_authorization(
                _registration(
                    _live_condition(
                        command=(
                            sys.executable,
                            str(APPROVED_WORKER),
                            "--transport",
                            "openai-compatible",
                            "--request-timeout-seconds",
                            "0",
                        )
                    )
                ),
                allow_network=True,
                environment={PROVIDER_CREDENTIAL_ENV: "secret"},
            )

    def test_mixed_batch_authorizes_only_live_condition(self):
        non_live = _live_condition(
            condition_id="mock",
            adapter_id="jsonl-reference-worker",
            command=(sys.executable, "reference-worker"),
            network_required=False,
        )
        registration = _registration(_live_condition(), non_live)
        validate_execution_authorization(
            registration,
            allow_network=True,
            environment={PROVIDER_CREDENTIAL_ENV: "secret"},
        )
        self.assertEqual(live_environment_names(registration.conditions[0]), (PROVIDER_CREDENTIAL_ENV,))
        self.assertEqual(live_environment_names(registration.conditions[1]), ())


if __name__ == "__main__":
    unittest.main()
